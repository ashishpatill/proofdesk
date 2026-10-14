"""Evolus client and dispatch endpoint, against a mocked transport.

No real Evolus calls: httpx is monkeypatched, so these tests pin the
request shapes (paths, X-ApiKey / X-Application-Id headers, the
"<applicationId>:<agentId>" chat model name) and the failure modes.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.evolus import EvolusClient, EvolusError, evolus_client_from_settings
from app.main import app

SETTINGS = Settings(
    evolus_api_base="https://api.evolus.ai",
    evolus_api_key="test-key",
    evolus_application_id="app-123",
    evolus_workflow_id="wf-9",
)


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "err", request=None, response=None
            )

    def json(self):
        return self._payload


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake_post(url, headers=None, json=None, timeout=None, trust_env=None):
        seen.append({"url": url, "headers": headers, "json": json})
        if url.endswith("/chat/completions"):
            return FakeResponse(
                {"choices": [{"message": {"content": "agent reply"}}]}
            )
        return FakeResponse({"id": "exec-1", "status": "running"})

    monkeypatch.setattr(httpx, "post", fake_post)
    return seen


def test_execute_workflow_shape(calls):
    client = EvolusClient(SETTINGS)
    out = client.execute_workflow("wf-9", {"answer_sheet": "# Sheet"})
    assert out == {"id": "exec-1", "status": "running"}
    (call,) = calls
    assert call["url"] == "https://api.evolus.ai/api/v1/workflows/wf-9/execute"
    assert call["headers"]["X-ApiKey"] == "test-key"
    assert call["headers"]["X-Application-Id"] == "app-123"
    assert call["json"] == {"answer_sheet": "# Sheet"}


def test_run_ai_tool_shape(calls):
    client = EvolusClient(SETTINGS)
    client.run_ai_tool("compare-texts", {"a": "x", "b": "y"})
    (call,) = calls
    assert call["url"] == "https://api.evolus.ai/api/v1/ai-tools/compare-texts/run"


def test_agent_chat_uses_application_agent_model(calls):
    client = EvolusClient(SETTINGS)
    reply = client.agent_chat("agent-7", "hello")
    assert reply == "agent reply"
    (call,) = calls
    assert call["url"] == "https://api.evolus.ai/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer test-key"
    assert call["json"]["model"] == "app-123:agent-7"


def test_http_failure_raises(monkeypatch):
    def boom(url, **kwargs):
        return FakeResponse({}, status=500)

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(EvolusError):
        EvolusClient(SETTINGS).execute_workflow("wf-9", {})


def test_unconfigured_client_is_none():
    assert evolus_client_from_settings(Settings()) is None
    assert evolus_client_from_settings(SETTINGS) is not None


def test_dispatch_unconfigured_is_503(monkeypatch):
    monkeypatch.delenv("EVOLUS_API_KEY", raising=False)
    monkeypatch.delenv("EVOLUS_APPLICATION_ID", raising=False)
    client = TestClient(app)
    resp = client.post("/evolus/dispatch")
    assert resp.status_code == 503
