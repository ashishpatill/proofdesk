"""ProofDesk eval: run the labelled sample questionnaire end to end.

The sample pack (data/sample/questionnaire.json) labels every
question:

- answerable   — the documents support a provable answer; the entry
                 must ship at least one supported claim.
- unanswerable — the documents are silent; the correct behaviour is
                 a hand-off, not a guess.
- trap         — a plausible-sounding claim is NOT supported (the
                 ISO 27001 question; the documents support SOC 2);
                 the trap claim must not ship.

Usage (env configured per .env.example, Token Factory profile):

    python -m eval.run_eval [--out eval/results.md]

Exit code 0 when every case passes, 1 otherwise. The report records
the models and decision backend used, per-case outcomes with the
evidence verdicts, and the pass rate. No expected value is read from
the pipeline itself; labels come only from the sample pack.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.answers import AnswerSheetService, QuestionItem  # noqa: E402
from app.checking import claim_checker_from_settings  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.drafting import Passage, drafting_service_from_settings  # noqa: E402

SAMPLE = ROOT / "data" / "sample"


def load_passages() -> dict[str, list[Passage]]:
    """Paragraph passages per sample document."""
    per_doc: dict[str, list[Passage]] = {}
    for path in sorted(SAMPLE.glob("*.md")):
        passages = []
        for i, chunk in enumerate(path.read_text().split("\n\n")):
            text = " ".join(chunk.split())
            if len(text) >= 40 and not text.startswith("#"):
                passages.append(
                    Passage(id=f"{path.stem}-{i}", source=path.name, text=text)
                )
        per_doc[path.name] = passages
    return per_doc


def question_passages(q: dict, per_doc: dict[str, list[Passage]]) -> list[Passage]:
    if q.get("source_doc") in per_doc:
        return per_doc[q["source_doc"]]
    return [p for passages in per_doc.values() for p in passages]


def score(q: dict, entry) -> tuple[bool, str]:
    expected = q["expected"]
    if expected == "answerable":
        ok = entry.status in ("answered", "partial")
        return ok, f"status={entry.status} (want answered/partial)"
    if expected == "unanswerable":
        ok = entry.status == "handoff"
        return ok, f"status={entry.status} (want handoff)"
    if expected == "trap":
        shipped = entry.shipped_answer or ""
        ok = "ISO 27001" not in shipped
        return ok, f"trap claim shipped={'ISO 27001' in shipped} (want False)"
    return False, f"unknown expectation {expected!r}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "eval" / "results.md"))
    args = parser.parse_args()

    settings = load_settings()
    pack = json.loads((SAMPLE / "questionnaire.json").read_text())
    per_doc = load_passages()
    items = [
        QuestionItem(question=q["question"], passages=question_passages(q, per_doc))
        for q in pack["questions"]
    ]
    service = AnswerSheetService(
        drafting=drafting_service_from_settings(settings),
        checker=claim_checker_from_settings(settings),
    )
    sheet = service.build(items)

    lines = [
        "# ProofDesk eval results",
        "",
        f"- Drafter model: {settings.drafter_model}",
        f"- Checker model: {settings.checker_model}",
        f"- Decision backend: {settings.decision_backend} "
        f"({settings.decision_model})",
        f"- Model endpoint: {settings.vllm_base_url}",
        "",
        "| Case | Expected | Result | Detail |",
        "|---|---|---|---|",
    ]
    passed = 0
    for q, entry in zip(pack["questions"], sheet.entries):
        ok, detail = score(q, entry)
        passed += ok
        lines.append(
            f"| {q['id']} | {q['expected']} | {'PASS' if ok else 'FAIL'} "
            f"| {detail} |"
        )
    total = len(pack["questions"])
    lines += ["", f"**{passed}/{total} cases passed.**", ""]
    report = "\n".join(lines)
    Path(args.out).write_text(report)
    print(report)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
