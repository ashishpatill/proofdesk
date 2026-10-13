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
