"""ProofDesk app entry point.

Commit 2: health endpoint backed by a vLLM probe, plus the vLLM
client the drafting and checking pipelines will use.
Commit 3: decision service wrapper (d3-lite with rules fallback)
behind a triage endpoint for incoming questionnaire questions.
"""

from fastapi import FastAPI
from pydantic import BaseModel

from app.config import load_settings
from app.decision import DecisionService
from app.vllm_client import VLLMClient

settings = load_settings()

app = FastAPI(title="ProofDesk", version="0.1.0")


class TriageRequest(BaseModel):
    questions: list[str]


class TriageItem(BaseModel):
    question: str
    category: str
    sensitivity: float
    answerable: float | None
    backend: str


@app.get("/health")
def health() -> dict:
    probe = VLLMClient(settings, timeout=3.0).probe()
    return {
        "status": "ok",
        "drafter_model": settings.drafter_model,
        "checker_model": settings.checker_model,
        "decision_model": settings.decision_model,
        "vllm": probe,
    }


@app.post("/triage", response_model=list[TriageItem])
def triage(request: TriageRequest) -> list[TriageItem]:
    results = DecisionService(settings, timeout=3.0).triage(request.questions)
    return [
        TriageItem(
            question=r.question,
            category=r.category,
            sensitivity=r.sensitivity,
            answerable=r.answerable,
            backend=r.backend,
        )
        for r in results
    ]
