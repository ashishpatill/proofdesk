"""vLLM client tests: 429 handling for rate-limited endpoints.

AMD Token Factory allows 30 requests per minute per key, so a burst
from the pipeline draws 429s. The client must honour Retry-After /
back off and succeed once the window clears, instead of failing the
call (and, before, the whole answer sheet).
"""

import httpx

from app.config import Settings
from app.vllm_client import VLLMClient


def make_client() -> VLLMClient:
    settings = Settings(
        vllm_base_url="http://models.invalid/v1",
        vllm_api_key="test-key",
        drafter_model="d",
        checker_model="c",
    )
    return VLLMClient(settings)


class _Resp:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)

    def json(self):
        return self._payload


def test_chat_retries_on_429_then_succeeds(monkeypatch):
    calls = {"n": 0}
    ok = _Resp(200, {"choices": [{"message": {"content": "done"}}]})

    def fake_post(*args, **kwargs):
        calls["n"] += 1
        return _Resp(429, headers={"Retry-After": "0"}) if calls["n"] < 3 else ok

    monkeypatch.setattr("app.vllm_client.httpx.post", fake_post)
    monkeypatch.setattr("app.vllm_client.time.sleep", lambda s: None)
    assert make_client().chat("m", []) == "done"
    assert calls["n"] == 3


_USAGE_PAYLOAD = {
    "rpm_limit": 20,
    "daily_cost_limit_usd": 1,
    "daily_cost_used_usd": 0.25,
    "daily_cost_remaining_usd": 0.75,
    "daily_reset_at": "2026-10-15T16:00:00.000Z",
}


def test_usage_parses_token_factory_payload(monkeypatch):
    monkeypatch.setattr(
        "app.vllm_client.httpx.get",
        lambda *a, **k: _Resp(200, _USAGE_PAYLOAD),
    )
    usage = make_client().usage()
    assert usage["remaining_usd"] == 0.75
    assert usage["limit_usd"] == 1.0
    assert usage["rpm_limit"] == 20
    assert usage["reset_at"].startswith("2026-10-15T16:00")


def test_usage_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(
        "app.vllm_client.httpx.get", lambda *a, **k: _Resp(404, {})
    )
    try:
        make_client().usage()
    except Exception as exc:
        assert "usage" in str(exc)
    else:
        raise AssertionError("usage() must raise when the endpoint errors")


def test_usage_raises_on_malformed_payload(monkeypatch):
    monkeypatch.setattr(
        "app.vllm_client.httpx.get", lambda *a, **k: _Resp(200, {"nope": 1})
    )
    try:
        make_client().usage()
    except Exception:
        pass
    else:
        raise AssertionError("usage() must raise on a malformed payload")


def test_chat_retries_on_timeout_then_succeeds(monkeypatch):
    calls = {"n": 0}
    ok = _Resp(200, {"choices": [{"message": {"content": "done"}}]})

    def fake_post(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ReadTimeout("slow endpoint")
        return ok

    monkeypatch.setattr("app.vllm_client.httpx.post", fake_post)
    monkeypatch.setattr("app.vllm_client.time.sleep", lambda s: None)
    assert make_client().chat("m", []) == "done"
    assert calls["n"] == 2
