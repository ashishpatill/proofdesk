"""Claim checking tests (commit 6).

Pinned behaviours: the pre-check bands route claims exactly as the
build pack says (high ships, low is cut, borderline escalates), an
escalated claim is settled by the checker model only, and a checker
that fails or talks nonsense produces "uncertain" — never a guess.
"""

import json

from fastapi.testclient import TestClient

from app.checking import CheckerService, ClaimChecker, split_claims
from app.config import Settings
from app.decision import (
    ClaimSupportResult,
    ClaimSupportService,
    RulesClaimSupportBackend,
)
from app.drafting import Claim, DraftResult, Passage
from app.main import app
from app.vllm_client import VLLMError

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


def test_split_claims_sentences_and_bullets():
    answer = (
        "Data is encrypted at rest. TLS 1.2 is enforced in transit!\n"
        "- Backups are retained for 30 days."
    )
    assert split_claims(answer) == [
        "Data is encrypted at rest.",
        "TLS 1.2 is enforced in transit!",
        "Backups are retained for 30 days.",
    ]


def test_split_claims_empty():
    assert split_claims("") == []
    assert split_claims("  \n ") == []


def test_rules_support_high_for_claim_from_passage():
    result = RulesClaimSupportBackend().claim_support(
        "Data is encrypted at rest using AES-256", PASSAGES[0].text
    )
    assert result.backend == "rules"
    assert result.probability >= 0.8
    assert result.supported is True


def test_rules_support_low_for_invented_claim():
    # The sample-data trap: ISO 27001 claimed, SOC 2 is what exists.
    result = RulesClaimSupportBackend().claim_support(
        "KiteMetric is ISO 27001 certified", PASSAGES[1].text
    )
    assert result.probability <= 0.3
    assert result.supported is False


def test_support_service_falls_back_when_d3_unreachable():
    settings = Settings(decision_base_url="http://127.0.0.1:9")
    result = ClaimSupportService(settings, timeout=1.0).claim_support(
        "Data is encrypted at rest using AES-256", PASSAGES[0].text
    )
    assert result.backend == "rules"


class StubSupport:
    """ClaimSupportService stand-in returning a fixed probability."""

    def __init__(self, probability: float) -> None:
        self.probability = probability
        self.calls = 0

    def claim_support(self, claim, passage):
        self.calls += 1
        return ClaimSupportResult(
            claim=claim,
            supported=self.probability >= 0.5,
            probability=self.probability,
            backend="stub",
        )


class FakeCheckerClient:
    def __init__(self, reply: str = "", error: bool = False) -> None:
        self.reply = reply
        self.error = error
        self.calls = 0

    def chat(self, model, messages, temperature=0.0, max_tokens=256):
        self.calls += 1
        if self.error:
            raise VLLMError("checker down")
        return self.reply


def make_checker(probability: float, checker_client) -> ClaimChecker:
    return ClaimChecker(
        support=StubSupport(probability),
        checker=CheckerService(checker_client, model="checker-m"),
    )


def draft_with(claims: list[Claim]) -> DraftResult:
    return DraftResult(question="q?", answer="", claims=claims, model="m")


def test_high_probability_ships_without_checker():
    fake = FakeCheckerClient()
    checked = make_checker(0.95, fake).check_draft(
        draft_with([Claim(text="c1", citations=["p1"])]), PASSAGES
    )
    v = checked.verdicts[0]
    assert v.route == "ship" and v.verdict == "supported"
    assert v.checked_by == "decision"
    assert fake.calls == 0
    assert len(checked.shipped_claims) == 1


def test_low_probability_is_cut_without_checker():
    fake = FakeCheckerClient()
    checked = make_checker(0.10, fake).check_draft(
        draft_with([Claim(text="c1", citations=["p1"])]), PASSAGES
    )
    v = checked.verdicts[0]
    assert v.route == "cut" and v.verdict == "unsupported"
    assert fake.calls == 0
    assert len(checked.blocked_claims) == 1


def test_borderline_escalates_and_checker_decides():
    fake = FakeCheckerClient(
        reply=json.dumps({"verdict": "supported", "reason": "passage states it"})
    )
    checked = make_checker(0.5, fake).check_draft(
        draft_with([Claim(text="c1", citations=["p1"])]), PASSAGES
    )
    v = checked.verdicts[0]
    assert v.route == "escalated" and v.verdict == "supported"
    assert v.checked_by == "checker"
    assert fake.calls == 1


def test_borderline_checker_can_block():
    fake = FakeCheckerClient(
        reply=json.dumps({"verdict": "unsupported", "reason": "not covered"})
    )
    checked = make_checker(0.5, fake).check_draft(
        draft_with([Claim(text="c1", citations=["p1"])]), PASSAGES
    )
    assert checked.verdicts[0].verdict == "unsupported"


def test_checker_failure_is_uncertain_never_guessed():
    fake = FakeCheckerClient(error=True)
    checked = make_checker(0.5, fake).check_draft(
        draft_with([Claim(text="c1", citations=["p1"])]), PASSAGES
    )
    v = checked.verdicts[0]
    assert v.verdict == "uncertain"
    assert v in checked.blocked_claims


def test_checker_malformed_output_is_uncertain():
    fake = FakeCheckerClient(reply="Looks supported to me!")
    checked = make_checker(0.5, fake).check_draft(
        draft_with([Claim(text="c1", citations=["p1"])]), PASSAGES
    )
    assert checked.verdicts[0].verdict == "uncertain"


def test_uncited_claim_escalates_without_precheck():
    support = StubSupport(0.99)
    fake = FakeCheckerClient(
        reply=json.dumps({"verdict": "unsupported", "reason": "no evidence"})
    )
    checker = ClaimChecker(
        support=support, checker=CheckerService(fake, model="checker-m")
    )
    checked = checker.check_draft(
        draft_with([Claim(text="c1", citations=[])]), PASSAGES
    )
    v = checked.verdicts[0]
    assert support.calls == 0
    assert v.precheck_probability is None
    assert v.route == "escalated" and v.verdict == "unsupported"


def test_check_endpoint_rules_path_ship_and_cut():
    resp = client.post(
        "/check",
        json={
            "question": "How is data encrypted, and are you ISO 27001 certified?",
            "claims": [
                {"text": "Data is encrypted at rest using AES-256",
                 "citations": ["p1"]},
                {"text": "KiteMetric is ISO 27001 certified",
                 "citations": ["p2"]},
            ],
            "passages": [
                {"id": p.id, "source": p.source, "text": p.text}
                for p in PASSAGES
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    verdicts = {v["text"]: v for v in body["claims"]}
    assert verdicts["Data is encrypted at rest using AES-256"]["verdict"] == "supported"
    assert verdicts["KiteMetric is ISO 27001 certified"]["verdict"] == "unsupported"
    assert body["summary"] == {
        "total": 2, "supported": 1, "unsupported": 1,
        "uncertain": 0, "escalated": 0,
    }
