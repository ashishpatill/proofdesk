from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_shape_without_vllm():
    # No vLLM server is running in the test environment: the app must
    # still answer, with the probe honestly reporting unreachable.
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["vllm"]["reachable"] is False
    assert body["vllm"]["models"] == []
