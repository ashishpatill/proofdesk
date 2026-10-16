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
    # Quota is reported when the endpoint serves usage data; with no
    # server at all it stays null and health still answers.
    assert body["quota"] is None


def test_decision_layer_label_names_the_deciding_backend():
    from app.config import Settings
    from app.main import _decision_layer_label

    # Under jev, DECISION_MODEL only drives triage; the pill must
    # name Jev, not the triage model.
    assert _decision_layer_label(Settings(decision_backend="jev")) == (
        "Jev (jev-1.13.0)"
    )
    assert _decision_layer_label(
        Settings(decision_backend="llm", decision_model="DeepSeek-V4.1-Flash")
    ) == "DeepSeek-V4.1-Flash"
    assert (
        _decision_layer_label(Settings(decision_backend="rules"))
        == "deterministic rules"
    )


def test_index_serves_ui():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "ProofDesk" in resp.text
    assert "checked against the source" in resp.text


def test_sample_endpoint_shape():
    resp = client.get("/sample")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 10
    first = items[0]
    assert first["question"]
    assert first["passages"] and first["passages"][0]["source"].endswith(".md")
    assert "expected" not in first
