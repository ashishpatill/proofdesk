"""LLM decision backend (DECISION_BACKEND=llm): strict JSON parsing,
validation, and the rules fallback when the model misbehaves."""

import pytest

from app.config import Settings
from app.decision import ClaimSupportService, DecisionService
import app.decision as decision_module

SETTINGS = Settings(
    decision_backend="llm",
    decision_model="DeepSeek-V4.1-Flash",
    vllm_base_url="https://example.invalid/v1",
)


class FakeClient:
    reply = ""

    def __init__(self, settings, timeout=30.0):
        pass

    def chat(self, model, messages, temperature=0.2, max_tokens=1024):
        return FakeClient.reply


@pytest.fixture
def fake_llm(monkeypatch):
    monkeypatch.setattr(decision_module, "VLLMClient", FakeClient)
    return FakeClient


def test_triage_parses_model_json(fake_llm):
    fake_llm.reply = (
        '{"category": "encryption", "sensitivity": 0.7, "answerable": 0.9}'
    )
    (result,) = DecisionService(SETTINGS).triage(
        ["Do you encrypt data at rest?"]
    )
    assert result.category == "encryption"
    assert result.sensitivity == 0.7
    assert result.answerable == 0.9
    assert result.backend == "llm"


def test_claim_support_parses_model_json(fake_llm):
    fake_llm.reply = '{"supported": true, "probability": 0.93}'
    result = ClaimSupportService(SETTINGS).claim_support(
        "Data is encrypted at rest.",
        "All stored data is encrypted at rest using AES-256.",
    )
    assert result.supported is True
    assert result.probability == 0.93
    assert result.backend == "llm"


def test_unknown_category_falls_back_to_rules(fake_llm):
    fake_llm.reply = (
        '{"category": "nonsense", "sensitivity": 0.5, "answerable": 0.5}'
    )
    (result,) = DecisionService(SETTINGS).triage(["Do you use MFA?"])
    assert result.backend == "rules"
    assert result.category == "access-control"


def test_malformed_json_falls_back_to_rules(fake_llm):
    fake_llm.reply = "The claim looks supported to me."
    result = ClaimSupportService(SETTINGS).claim_support(
        "We encrypt data at rest.", "We encrypt data at rest."
    )
    assert result.backend == "rules"


def test_out_of_range_score_falls_back_to_rules(fake_llm):
    fake_llm.reply = '{"supported": true, "probability": 1.7}'
    result = ClaimSupportService(SETTINGS).claim_support(
        "We encrypt data at rest.", "We encrypt data at rest."
    )
    assert result.backend == "rules"
