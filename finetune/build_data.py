"""Build the claim-support fine-tune dataset (Option C).

Labels are correct by construction: supported claims are statements
taken from the documents; unsupported ones are programmatic
corruptions of those statements (number swaps, technology swaps,
scope inflation, qualifier drops, cross-document mismatches, and
absence claims). No LLM labelling, no hand-waved ground truth.

Train split comes from the KiteMetric sample pack; the validation
split comes from a different fictional company (Northwind, in
finetune/unseen_docs/) that training never sees, so validation
measures generalisation, not memorisation.

Output (MLX-LM chat format + a backend-agnostic eval file):
    finetune/data/train.jsonl
    finetune/data/valid.jsonl
    finetune/data/eval_claims.jsonl   (from the validation company)
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.decision import _CLAIM_SUPPORT_SYSTEM  # noqa: E402

random.seed(20261015)
OUT = ROOT / "finetune" / "data"
OUT.mkdir(parents=True, exist_ok=True)

NUMBER_RE = re.compile(r"\b(\d+(?:\.\d+)?)\b")
TECH_SWAPS = [
    ("AES-256", "AES-128"),
    ("AES-256-GCM", "AES-128"),
    ("TLS 1.3", "TLS 1.0"),
    ("TLS 1.2", "SSL 3.0"),
    ("SOC 2 Type I", "ISO 27001"),
    ("SOC 2 Type II", "ISO 27001"),
    ("SOC 2", "ISO 27001"),
    ("FIDO2 hardware keys", "SMS codes"),
    ("phishing-resistant hardware keys (FIDO2)", "SMS codes"),
    ("multi-factor authentication (TOTP)", "passwords alone"),
    ("TOTP", "SMS codes"),
]
SCOPE_SWAPS = [
    ("annually", "monthly"),
    ("annual", "monthly"),
    ("twice a year", "every month"),
    ("weekly", "daily"),
    ("every 6 hours", "every 30 days"),
    ("within 24 hours", "within 90 days"),
    ("within 7 days", "within 180 days"),
]
QUALIFIERS = [
    "for paid tiers",
    "for enterprise customers",
    "in the EU (Frankfurt region)",
    "business ",
    "on request",
]


def doc_units(path: Path) -> list[tuple[str, str]]:
    """(passage, statement) pairs from one markdown document.

    Bullet lines are self-contained facts (passage = the bullet);
    prose is split into sentences with their paragraph as passage.
    Heading lines never swallow the content that follows them.
    """
    pairs: list[tuple[str, str]] = []
    para: list[str] = []

    def flush() -> None:
        if not para:
            return
        text = " ".join(para)
        para.clear()
        if len(text) < 40:
            return
        for sentence in re.split(r"(?<=[.!])\s+", text):
            sentence = sentence.strip()
            if len(sentence) >= 40:
                pairs.append((text, sentence))

    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line.startswith("#"):
            flush()
        elif line.startswith("- ") or line.startswith("* "):
            flush()
            stmt = line[2:].strip()
            if len(stmt) >= 30:
                pairs.append((stmt, stmt.rstrip(".") + "."))
        elif not line:
            flush()
        else:
            para.append(line)
    flush()
    return pairs


def corrupt_number(stmt: str) -> str | None:
    nums = NUMBER_RE.findall(stmt)
    if not nums:
        return None

    def repl(m: re.Match) -> str:
        v = float(m.group(1))
        nv = v * 2 if v >= 10 else v + 7
        return str(int(nv)) if float(nv).is_integer() else str(nv)

    return NUMBER_RE.sub(repl, stmt, count=1)


def swap_from(table, stmt):
    for old, new in table:
        if old in stmt:
            return stmt.replace(old, new, 1)
    return None


def drop_qualifier(stmt: str) -> str | None:
    for q in QUALIFIERS:
        if q in stmt:
            out = stmt.replace(q, "").replace("  ", " ").replace(" .", ".")
            return out[0].upper() + out[1:] if out else None
    return None


def example(claim: str, passage: str, supported: bool, p: float) -> dict:
    target = json.dumps({"supported": supported, "probability": round(p, 2)})
    return {
        "messages": [
            {"role": "system", "content": _CLAIM_SUPPORT_SYSTEM},
            {"role": "user", "content": f"Claim: {claim}\n\nPassage: {passage}"},
            {"role": "assistant", "content": target},
        ],
        "_label": {"claim": claim, "passage": passage,
                   "supported": supported, "probability": round(p, 2)},
    }


def build(pairs: list[tuple[str, str]], all_pairs) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(claim: str, passage: str, supported: bool, p: float) -> None:
        key = (claim, passage)
        if key in seen:
            return
        seen.add(key)
        rows.append(example(claim, passage, supported, p))

    passages = [p for p, _ in all_pairs]
    for passage, stmt in pairs:
        # Supported at two context widths: the full block, and the
        # statement's own sentence as a tight passage.
        add(stmt, passage, True, random.uniform(0.87, 0.98))
        add(stmt, stmt, True, random.uniform(0.85, 0.97))
        c = corrupt_number(stmt)
        if c and c != stmt:
            add(c, passage, False, random.uniform(0.02, 0.22))
        c = swap_from(TECH_SWAPS, stmt)
        if c and c != stmt:
            add(c, passage, False, random.uniform(0.02, 0.2))
        c = swap_from(SCOPE_SWAPS, stmt)
        if c and c != stmt:
            add(c, passage, False, random.uniform(0.05, 0.28))
        cnum, ctech = corrupt_number(stmt), swap_from(TECH_SWAPS, stmt)
        if cnum and ctech and cnum != stmt and ctech != stmt:
            both = ctech.replace(
                NUMBER_RE.search(stmt).group(0), NUMBER_RE.search(cnum).group(0)
            ) if NUMBER_RE.search(stmt) and NUMBER_RE.search(cnum) else None
            if both and both != stmt:
                add(both, passage, False, random.uniform(0.01, 0.15))
        c = drop_qualifier(stmt)
        if c and c != stmt:
            # Dropping a qualifier overstates the claim: borderline,
            # which the desk escalates rather than ships or cuts.
            add(c, passage, False, random.uniform(0.4, 0.6))
        if NUMBER_RE.search(stmt) or swap_from(TECH_SWAPS, stmt):
            others = random.sample(
                [p for p in passages if p != passage],
                k=min(2, len(passages) - 1),
            )
            for other in others:
                add(stmt, other, False, random.uniform(0.03, 0.25))
        add(f"The documents do not mention whether the following holds: {stmt}",
            passage, False, random.uniform(0.03, 0.2))
    return rows


def main() -> int:
    train_pairs: list[tuple[str, str]] = []
    for path in sorted((ROOT / "data" / "sample").glob("*.md")):
        train_pairs += doc_units(path)
    gen_dir = ROOT / "finetune" / "gen_docs"
    if gen_dir.exists():
        for path in sorted(gen_dir.glob("*.md")):
            train_pairs += doc_units(path)
    valid_pairs: list[tuple[str, str]] = []
    for path in sorted((ROOT / "finetune" / "unseen_docs").glob("*.md")):
        valid_pairs += doc_units(path)

    train = build(train_pairs, train_pairs)
    valid = build(valid_pairs, valid_pairs)
    random.shuffle(train)
    random.shuffle(valid)

    def dump(rows, name):
        with open(OUT / name, "w") as fh:
            for row in rows:
                fh.write(json.dumps({k: v for k, v in row.items()
                                     if k != "_label"}) + "\n")

    dump(train, "train.jsonl")
    dump(valid, "valid.jsonl")
    with open(OUT / "eval_claims.jsonl", "w") as fh:
        for row in valid:
            fh.write(json.dumps(row["_label"]) + "\n")

    sup = sum(1 for r in train if r["_label"]["supported"])
    print(f"train: {len(train)} examples ({sup} supported, "
          f"{len(train) - sup} not) from {len(train_pairs)} statements")
    sup = sum(1 for r in valid if r["_label"]["supported"])
    print(f"valid: {len(valid)} examples ({sup} supported, "
          f"{len(valid) - sup} not) from {len(valid_pairs)} statements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
