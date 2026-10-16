"""Decision service tests.

No d3 sidecar runs in the test environment, so these tests pin the
two behaviours that must hold without one: the service falls back to
the rules backend, and the rules backend's answers are honest
(answerable is None, never an invented score).
"""

from fastapi.testclient import TestClient

from app.config import Settings
from app.decision import DecisionService, RulesDecisionBackend
from app.main import app

client = TestClient(app)


def test_rules_category_and_sensitivity():
    result = RulesDecisionBackend().triage(
        "Do you encrypt customer data at rest, and how are encryption keys managed?"
    )
    assert result.category == "encryption"
    assert result.sensitivity >= 0.25  # "customer data" hit
    assert result.backend == "rules"


def test_rules_access_control_category():
    result = RulesDecisionBackend().triage(
        "Is multi-factor authentication enforced for all employees?"
    )
    assert result.category == "access-control"


def test_rules_answerable_is_unknown_not_invented():
    result = RulesDecisionBackend().triage("What is your uptime SLA?")
    assert result.answerable is None


def test_service_falls_back_when_d3_unreachable():
    # Port 9 (discard) has no listener: the HTTP backend must fail and
    # the service must still answer, via rules.
    settings = Settings(decision_base_url="http://127.0.0.1:9")
    results = DecisionService(settings, timeout=1.0).triage(
        ["Do you have a documented incident response plan?"]
    )
    assert len(results) == 1
    assert results[0].backend == "rules"
    assert results[0].category == "incident-response"


def test_triage_endpoint_shape_without_d3():
    resp = client.post(
        "/triage",
        json={"questions": ["How long do you retain backups?"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["category"] == "data-retention"
    assert body[0]["backend"] == "rules"
    assert body[0]["answerable"] is None


# ------------------------------------------------------------------
# Jev backend: the wire shape is pinned against a fake transport —
# state is the passage, one Noul question carries the claim and the
# absence rule, the model is pinned, and the key travels as a
# bearer header. Failures must degrade to the rules fallback,
# never to an invented score.
# ------------------------------------------------------------------

import httpx

from app.decision import ClaimSupportService, JevClaimSupportBackend


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _jev_settings(**overrides):
    base = {"decision_backend": "jev", "typesafe_api_key": "test-key"}
    base.update(overrides)
    return Settings(**base)


def test_jev_claim_support_maps_noul_probability(monkeypatch):
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, json=json, headers=headers)
        return _FakeResponse(
            {"answers": {"support": {"type": "noul", "noul": 0.93}}}
        )

    monkeypatch.setattr("app.decision.httpx.post", fake_post)
    result = JevClaimSupportBackend(_jev_settings()).claim_support(
        "Data at rest is encrypted with AES-256.",
        "All data at rest is encrypted with AES-256 (AWS KMS).",
    )
    assert result.backend == "jev"
    assert result.probability == 0.93
    assert result.supported is True
    assert seen["url"] == "https://api.typesafe.ai/v1/systemone"
    assert seen["headers"]["Authorization"] == "Bearer test-key"
    assert seen["json"]["model"] == "jev-1.13.0"
    assert seen["json"]["state"].startswith("All data at rest")
    question = seen["json"]["questions"]["support"]
    assert question["type"] == "noul"
    assert "AES-256" in question["instructions"]
    assert "exclusively" in question["instructions"]  # absence rule


def test_jev_claim_support_low_probability_is_unsupported(monkeypatch):
    monkeypatch.setattr(
        "app.decision.httpx.post",
        lambda *a, **k: _FakeResponse(
            {"answers": {"support": {"type": "noul", "noul": 0.12}}}
        ),
    )
    result = JevClaimSupportBackend(_jev_settings()).claim_support(
        "We are ISO 27001 certified.", "We hold a SOC 2 Type II report."
    )
    assert result.supported is False
    assert result.probability == 0.12


def test_jev_missing_key_falls_back_to_rules():
    service = ClaimSupportService(_jev_settings(typesafe_api_key=""))
    result = service.claim_support(
        "Data is encrypted.", "Data is encrypted at rest."
    )
    assert result.backend == "rules"


def test_jev_transport_error_falls_back_to_rules(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("app.decision.httpx.post", boom)
    service = ClaimSupportService(_jev_settings())
    result = service.claim_support(
        "Data is encrypted.", "Data is encrypted at rest."
    )
    assert result.backend == "rules"


def test_jev_out_of_range_probability_falls_back_to_rules(monkeypatch):
    monkeypatch.setattr(
        "app.decision.httpx.post",
        lambda *a, **k: _FakeResponse(
            {"answers": {"support": {"type": "noul", "noul": 1.4}}}
        ),
    )
    service = ClaimSupportService(_jev_settings())
    result = service.claim_support(
        "Data is encrypted.", "Data is encrypted at rest."
    )
    assert result.backend == "rules"
