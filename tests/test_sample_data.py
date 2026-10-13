"""Sample data pack integrity.

The pack is the ground truth the demo and the eval harness run
against, so its shape is pinned: the documents exist, the
questionnaire parses, every answerable question names a real
document, and the hand-off and trap cases the build plan requires
are present in the promised numbers.
"""

import json
from pathlib import Path

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample"

EXPECTED_DOCS = [
    "company.md",
    "security-policy.md",
    "data-retention-policy.md",
    "incident-response-plan.md",
    "dpa-summary.md",
    "subprocessors.md",
    "product-faq.md",
    "limits-and-pricing.md",
]


def _questionnaire() -> dict:
    return json.loads((SAMPLE / "questionnaire.json").read_text())


def test_all_documents_exist_and_are_nonempty():
    for name in EXPECTED_DOCS:
        path = SAMPLE / name
        assert path.is_file(), f"missing sample doc: {name}"
        assert len(path.read_text().strip()) > 100, f"suspiciously thin: {name}"


def test_questionnaire_shape_and_counts():
    questions = _questionnaire()["questions"]
    assert 12 <= len(questions) <= 15
    by_expected = {}
    for q in questions:
        by_expected[q["expected"]] = by_expected.get(q["expected"], 0) + 1
    assert by_expected.get("unanswerable", 0) >= 2
    assert by_expected.get("trap", 0) >= 1
    assert by_expected.get("answerable", 0) >= 8


def test_answerable_questions_name_real_documents():
    for q in _questionnaire()["questions"]:
        if q["expected"] == "answerable":
            assert (SAMPLE / q["source_doc"]).is_file(), q["id"]


def test_ids_unique_and_trap_is_the_certification_question():
    questions = _questionnaire()["questions"]
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids))
    traps = [q for q in questions if q["expected"] == "trap"]
    assert any("ISO 27001" in q["question"] for q in traps)
