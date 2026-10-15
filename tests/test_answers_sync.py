"""POST /answers/sync: the parallel UI runner assembles the sheet
client-side (parallel requests may land on different instances) and
syncs the merged sheet back, so the review queue and dispatch see
the whole run. Counts in the payload are ignored and recomputed."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

SHEET = {
    "entries": [
        {
            "question": "Is data encrypted at rest?",
            "status": "answered",
            "shipped_answer": "Data at rest uses AES-256.",
            "evidence_trail": [
                {
                    "claim": "Data at rest uses AES-256.",
                    "verdict": "supported",
                    "citations": ["p1"],
                    "sources": ["security.md"],
                    "checked_by": "decision",
                    "precheck_probability": 0.97,
                    "reason": "pre-check probability 0.97 >= 0.8",
                }
            ],
            "flags": [],
        },
        {
            "question": "Will you sign a HIPAA BAA?",
            "status": "handoff",
            "shipped_answer": "",
            "evidence_trail": [],
            "flags": ["the supplied documents do not answer this question"],
        },
    ],
    "counts": {"bogus": 1},
    "markdown": "client markdown is ignored",
}


def test_sync_stores_sheet_and_recomputes_counts():
    resp = client.post("/answers/sync", json=SHEET)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["entries"]) == 2
    assert body["counts"]["answered"] == 1
    assert body["counts"]["handoff"] == 1
    assert body["counts"]["claims_shipped"] == 1
    assert "bogus" not in body["counts"]

    stored = client.get("/answers")
    assert stored.status_code == 200
    assert stored.json()["entries"][0]["question"] == SHEET["entries"][0]["question"]


def test_review_queue_reflects_synced_sheet():
    client.post("/answers/sync", json=SHEET)
    queue = client.get("/review-queue")
    assert queue.status_code == 200
    questions = [item["question"] for item in queue.json()]
    assert questions == ["Will you sign a HIPAA BAA?"]
