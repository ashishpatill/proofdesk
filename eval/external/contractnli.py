"""External eval stage 1: ContractNLI claim-support benchmark.

Grades ProofDesk's claim-support backends (rules / llm / jev) on
real human judgements instead of our own sample pack. Dataset:
Stanford ContractNLI (Koreeda & Manning, EMNLP 2021 Findings),
released under CC BY 4.0 — see experiments/external-contractnli.md
for source, licence and attribution.

Shape bridge: ProofDesk claim support takes (claim, passage);
ContractNLI is document-level with gold evidence spans. Primary
mode is evidence-span mode: the hypothesis is the claim and the
passage is its gold evidence spans joined. NotMentioned items
have no gold spans by definition; for those the passage is the
top BM25 span from the same contract (the passage a real pipeline
would most plausibly put in front of the checker), or empty when
no span shares vocabulary with the hypothesis. The mode is
recorded per item (`passage_mode`).

Label mapping, fail-closed like the product: Entailment ->
supported; Contradiction and NotMentioned -> not supported.

Usage:
    python -m eval.external.contractnli build --data-dir <dir>
    python -m eval.external.contractnli grade --backend jev
    python -m eval.external.contractnli grade --backend llm \
        --subset stratified300

`build` reads the official test.json and writes the derived
pairs file under eval/external/data/. `grade` writes per-item
results under eval/external/results/ and prints a summary.
Backend credentials come from the environment via app.config,
exactly as the app reads them.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.config import load_settings
from app.decision import ClaimSupportService
from app.drafting import Passage
from app.retrieval import Retriever

HERE = Path(__file__).resolve().parent
PAIRS_PATH = HERE / "data" / "contractnli_test_pairs.jsonl"
RESULTS_DIR = HERE / "results"

SUPPORTED = "Entailment"


def _span_texts(doc: dict) -> list[str]:
    text = doc["text"]
    return [text[start:end] for start, end in doc["spans"]]


def build_pairs(data_dir: Path) -> list[dict]:
    raw = json.loads((data_dir / "test.json").read_text(encoding="utf-8"))
    labels = raw["labels"]
    pairs: list[dict] = []
    for doc in raw["documents"]:
        spans = _span_texts(doc)
        annotations = doc["annotation_sets"][0]["annotations"]
        span_passages = [
            Passage(id=f"span-{i}", source=doc["file_name"], text=t)
            for i, t in enumerate(spans)
        ]
        retriever = Retriever(span_passages)
        for hyp_id, ann in annotations.items():
            hypothesis = labels[hyp_id]["hypothesis"]
            gold = ann["choice"]
            if gold == "NotMentioned":
                top = retriever.retrieve(hypothesis, k=1)
                if top:
                    passage, mode = top[0].text, "bm25-top1"
                else:
                    passage, mode = "", "none"
            else:
                passage = "\n".join(spans[i] for i in ann["spans"])
                mode = "gold-spans"
            pairs.append(
                {
                    "doc_id": doc["id"],
                    "hyp_id": hyp_id,
                    "hypothesis": hypothesis,
                    "gold": gold,
                    "passage": passage,
                    "passage_mode": mode,
                }
            )
    return pairs


def stratified_subset(pairs: list[dict], total: int, seed: int = 42) -> list[dict]:
    """Proportional-per-class deterministic sample of `total`."""
    by_class: dict[str, list[dict]] = {}
    for p in pairs:
        by_class.setdefault(p["gold"], []).append(p)
    rng = random.Random(seed)
    chosen: list[dict] = []
    for gold, items in sorted(by_class.items()):
        take = round(total * len(items) / len(pairs))
        pool = list(items)
        rng.shuffle(pool)
        chosen.extend(pool[:take])
    return chosen[:total]


def _percentiles(values: list[float]) -> dict:
    if not values:
        return {}
    values = sorted(values)

    def pct(q: float) -> float:
        return values[min(len(values) - 1, int(q * len(values)))]

    return {
        "n": len(values),
        "p10": round(pct(0.10), 3),
        "p25": round(pct(0.25), 3),
        "median": round(statistics.median(values), 3),
        "p75": round(pct(0.75), 3),
        "p90": round(pct(0.90), 3),
    }


def summarise(rows: list[dict]) -> dict:
    def acc(rs: list[dict]) -> float:
        return round(sum(r["correct"] for r in rs) / len(rs), 4) if rs else 0.0

    by_gold: dict[str, list[dict]] = {}
    for r in rows:
        by_gold.setdefault(r["gold"], []).append(r)
    probs: dict[str, list[float]] = {}
    for r in rows:
        if r.get("probability") is not None:
            probs.setdefault(r["gold"], []).append(r["probability"])
    return {
        "n": len(rows),
        "accuracy": acc(rows),
        "per_class": {g: {"n": len(rs), "accuracy": acc(rs)} for g, rs in sorted(by_gold.items())},
        "false_approvals": sum(
            1 for r in rows if r["gold"] != SUPPORTED and r["predicted_supported"]
        ),
        "fallbacks_to_rules": sum(1 for r in rows if r.get("backend_actual") == "rules" and r.get("backend_requested") != "rules"),
        "latency_ms_median": (
            round(statistics.median([r["ms"] for r in rows]), 1) if rows else None
        ),
        "probability_by_gold": {g: _percentiles(v) for g, v in sorted(probs.items())},
    }


def grade(backend: str, subset: str | None, workers: int = 4) -> dict:
    pairs = [
        json.loads(line)
        for line in PAIRS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if subset == "stratified300":
        pairs = stratified_subset(pairs, 300)
    settings = load_settings()
    if settings.decision_backend != backend:
        raise SystemExit(
            f"DECISION_BACKEND is {settings.decision_backend!r}, not "
            f"{backend!r}: set the environment for the backend you "
            "mean to grade."
        )
    service = ClaimSupportService(settings)

    def run_one(pair: dict) -> dict:
        t0 = time.perf_counter()
        result = service.claim_support(pair["hypothesis"], pair["passage"])
        ms = (time.perf_counter() - t0) * 1000
        predicted = bool(result.supported)
        return {
            "doc_id": pair["doc_id"],
            "hyp_id": pair["hyp_id"],
            "gold": pair["gold"],
            "passage_mode": pair["passage_mode"],
            "predicted_supported": predicted,
            "correct": predicted == (pair["gold"] == SUPPORTED),
            "probability": result.probability,
            "backend_requested": backend,
            "backend_actual": result.backend,
            "ms": round(ms, 1),
        }

    RESULTS_DIR.mkdir(exist_ok=True)
    suffix = f"_{subset}" if subset else ""
    out = RESULTS_DIR / f"contractnli_{backend}{suffix}.jsonl"
    # Stream rows to disk as they land: a full-split run is
    # thousands of calls, and losing it all to one interrupted
    # process would waste the quota it already spent.
    out.write_text("", encoding="utf-8")
    lock = threading.Lock()
    rows: list[dict] = []

    def collect(pair: dict) -> None:
        row = run_one(pair)
        with lock:
            rows.append(row)
            with out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(collect, p) for p in pairs]
        for f in as_completed(futures):
            f.result()
    summary = summarise(rows)
    summary["backend"] = backend
    summary["subset"] = subset or "full"
    print(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--data-dir", type=Path, required=True)
    g = sub.add_parser("grade")
    g.add_argument("--backend", choices=["rules", "llm", "jev"], required=True)
    g.add_argument("--subset", choices=["stratified300"], default=None)
    g.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.cmd == "build":
        pairs = build_pairs(args.data_dir)
        PAIRS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PAIRS_PATH.write_text(
            "\n".join(json.dumps(p) for p in pairs) + "\n", encoding="utf-8"
        )
        counts: dict[str, int] = {}
        for p in pairs:
            counts[p["gold"]] = counts.get(p["gold"], 0) + 1
        print(f"wrote {len(pairs)} pairs to {PAIRS_PATH}: {counts}")
    else:
        grade(args.backend, args.subset, args.workers)


if __name__ == "__main__":
    main()
