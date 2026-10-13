"""Drafting pipeline tests, against a fake drafter.

The behaviours pinned here are the trust rules of the pipeline: a
draft is only as good as its citations, citations must trace to the
supplied passages, and malformed model output fails loudly instead
of being repaired into something plausible.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.drafting import DraftingError, DraftingService, Passage
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
        source="security-policy.md",
        text="TLS 1.2 or higher is enforced for data in transit.",
    ),
]


class FakeClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def chat(self, model, messages, temperature=0.2, max_tokens=1024):
        self.calls += 1
        return self.reply


def test_draft_parses_claims_with_valid_citations():
    reply = json.dumps(
        {
            "answer": "Data is encrypted at rest and in transit.",
            "claims": [
                {"text": "Encrypted at rest with AES-256", "citations": ["p1"]},
                {"text": "TLS 1.2+ in transit", "citations": ["p2"]},
            ],
        }
    )
    result = DraftingService(FakeClient(reply), model="m").draft(
        "How do you encrypt data?", PASSAGES
    )
    assert result.answer.startswith("Data is encrypted")
    assert [c.citations for c in result.claims] == [["p1"], ["p2"]]


def test_draft_rejects_unknown_citation():
    reply = json.dumps(
        {
            "answer": "We are ISO 27001 certified.",
            "claims": [
                {"text": "ISO 27001 certified", "citations": ["p9"]},
            ],
        }
    )
    with pytest.raises(DraftingError):
        DraftingService(FakeClient(reply), model="m").draft(
            "Are you ISO 27001 certified?", PASSAGES
        )


def test_draft_rejects_malformed_output():
    with pytest.raises(DraftingError):
        DraftingService(FakeClient("Sure! We encrypt things."), model="m").draft(
            "How do you encrypt data?", PASSAGES
        )


def test_no_passages_means_no_draft_and_no_call():
    fake = FakeClient("{}")
    result = DraftingService(fake, model="m").draft("Anything?", [])
    assert result.answer == ""
    assert result.claims == []
    assert fake.calls == 0


def test_draft_endpoint_fails_honestly_without_vllm():
    # Nothing serves vLLM in the test environment: the endpoint must
    # return 502, never an invented answer.
    resp = client.post(
        "/draft",
        json={
            "question": "How do you encrypt data?",
            "passages": [
                {"id": "p1", "source": "s.md", "text": "AES-256 at rest."}
            ],
        },
    )
    assert resp.status_code == 502
