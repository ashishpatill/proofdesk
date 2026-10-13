"""ProofDesk app entry point.

Commit 2: health endpoint backed by a vLLM probe, plus the vLLM
client the drafting and checking pipelines will use.
Commit 3: decision service wrapper (d3-lite with rules fallback)
behind a triage endpoint for incoming questionnaire questions.
Commit 5: drafting endpoint. The drafter writes an answer with
citations from supplied passages only; untraceable citations and
malformed output fail the request instead of shipping.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.config import load_settings
from app.decision import DecisionService
from app.drafting import (
    DraftingError,
    Passage,
    drafting_service_from_settings,
)
from app.vllm_client import VLLMClient, VLLMError

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


class PassageIn(BaseModel):
    id: str
    source: str
    text: str


class DraftRequest(BaseModel):
    question: str
    passages: list[PassageIn]


class ClaimOut(BaseModel):
    text: str
    citations: list[str]


class DraftOut(BaseModel):
    question: str
    answer: str
    claims: list[ClaimOut]
    model: str


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


@app.post("/draft", response_model=DraftOut)
def draft(request: DraftRequest) -> DraftOut:
    passages = [
        Passage(id=p.id, source=p.source, text=p.text) for p in request.passages
    ]
    service = drafting_service_from_settings(settings)
    try:
        result = service.draft(request.question, passages)
    except (DraftingError, VLLMError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return DraftOut(
        question=result.question,
        answer=result.answer,
        claims=[
            ClaimOut(text=c.text, citations=c.citations) for c in result.claims
        ],
        model=result.model,
    )
