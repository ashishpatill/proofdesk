"""Answer sheet and review queue tests (commit 7).

The whole pipeline runs on fakes here. Pinned behaviours: only
supported claims reach the shipped answer, blocked claims are
listed in the review queue with their reasons, questions the
documents cannot answer become handoffs, and every shipped claim
keeps an evidence trail back to its source document.
"""

from fastapi.testclient import TestClient

from app.answers import (
    AnswerSheetService,
    QuestionItem,
    render_markdown,
    review_queue,
)
from app.checking import ClaimChecker
from app.decision import RulesClaimSupportBackend
from app.drafting import Claim, DraftResult, Passage
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

PASSAGES = [
    Passage(
        id="p1",
        source="security-policy.md",
        text="Data is encrypted at rest using AES-256.",
    ),
    Passage(
        id="p2",
        source="compliance.md",
        text="KiteMetric holds SOC 2 Type I, audited March 2026.",
    ),
]


class FakeDrafting:
    """DraftingService stand-in: fixed draft per question."""

    def __init__(self, drafts: dict[str, DraftResult]) -> None:
        self._drafts = drafts

    def draft(self, question, passages):
        return self._drafts[question]


class NoChecker:
    """CheckerService stand-in that must not be called in these
    tests (the rules pre-check settles every claim used here)."""

    def check(self, claim, passages):  # pragma: no cover
        raise AssertionError("checker should not be called")


def make_service(drafts) -> AnswerSheetService:
    checker = ClaimChecker(
        support=RulesClaimSupportBackend(), checker=NoChecker()
    )
    return AnswerSheetService(drafting=FakeDrafting(drafts), checker=checker)


def test_answered_entry_ships_with_evidence_trail():
    drafts = {
        "How is data encrypted?": DraftResult(
            question="How is data encrypted?",
            answer="Data is encrypted at rest using AES-256.",
            claims=[
                Claim(
                    text="Data is encrypted at rest using AES-256",
                    citations=["p1"],
                )
            ],
            model="fake",
        )
    }
    sheet = make_service(drafts).build(
        [QuestionItem(question="How is data encrypted?", passages=PASSAGES)]
    )
    entry = sheet.entries[0]
    assert entry.status == "answered"
    assert "AES-256" in entry.shipped_answer
    assert entry.evidence_trail[0].sources == ["security-policy.md"]
    assert entry.evidence_trail[0].verdict == "supported"
    assert review_queue(sheet) == []
    assert sheet.counts["claims_shipped"] == 1


def test_trap_claim_is_blocked_and_queued():
    # The demo catch: an ISO 27001 claim against SOC 2 evidence.
    drafts = {
        "Are you ISO 27001 certified?": DraftResult(
            question="Are you ISO 27001 certified?",
            answer="KiteMetric is ISO 27001 certified and holds SOC 2 Type I.",
            claims=[
                Claim(
                    text="KiteMetric holds SOC 2 Type I audited March 2026",
                    citations=["p2"],
                ),
                Claim(
                    text="KiteMetric is ISO 27001 certified",
                    citations=["p2"],
                ),
            ],
            model="fake",
        )
    }
    sheet = make_service(drafts).build(
        [QuestionItem(question="Are you ISO 27001 certified?", passages=PASSAGES)]
    )
    entry = sheet.entries[0]
    assert entry.status == "partial"
    assert "SOC 2 Type I" in entry.shipped_answer
    assert "ISO 27001 certified" not in entry.shipped_answer
    queue = review_queue(sheet)
    assert len(queue) == 1
    assert queue[0].question == "Are you ISO 27001 certified?"
    assert queue[0].blocked_claims[0].claim == "KiteMetric is ISO 27001 certified"
    assert sheet.counts["claims_blocked"] == 1


def test_unanswerable_question_is_a_handoff():
    drafts = {
        "Do you offer on-premises deployment?": DraftResult(
            question="Do you offer on-premises deployment?",
            answer="",
            claims=[],
            model="fake",
        )
    }
    sheet = make_service(drafts).build(
        [
            QuestionItem(
                question="Do you offer on-premises deployment?",
                passages=PASSAGES,
            )
        ]
    )
    entry = sheet.entries[0]
    assert entry.status == "handoff"
    assert entry.shipped_answer == ""
    queue = review_queue(sheet)
    assert len(queue) == 1
    assert "handed off" in queue[0].reasons[0]


def test_markdown_render_has_question_answer_and_sources():
    drafts = {
        "How is data encrypted?": DraftResult(
            question="How is data encrypted?",
            answer="Data is encrypted at rest using AES-256.",
            claims=[
                Claim(
                    text="Data is encrypted at rest using AES-256",
                    citations=["p1"],
                )
            ],
            model="fake",
        )
    }
    sheet = make_service(drafts).build(
        [QuestionItem(question="How is data encrypted?", passages=PASSAGES)]
    )
    md = render_markdown(sheet)
    assert "# ProofDesk answer sheet" in md
    assert "## How is data encrypted?" in md
    assert "security-policy.md" in md
    assert "[supported]" in md


def test_answers_endpoints_before_any_build_return_404():
    assert client.get("/answers").status_code == 404
    assert client.get("/review-queue").status_code == 404


def test_questionnaire_endpoint_fails_honestly_without_vllm():
    resp = client.post(
        "/questionnaire",
        json={
            "items": [
                {
                    "question": "How is data encrypted?",
                    "passages": [
                        {"id": "p1", "source": "s.md", "text": "AES-256."}
                    ],
                }
            ]
        },
    )
    assert resp.status_code == 502
