"""ProofDesk app entry point.

Commit 2: health endpoint backed by a vLLM probe, plus the vLLM
client the drafting and checking pipelines will use.
Commit 3: decision service wrapper (d3-lite with rules fallback)
behind a triage endpoint for incoming questionnaire questions.
Commit 5: drafting endpoint. The drafter writes an answer with
citations from supplied passages only; untraceable citations and
malformed output fail the request instead of shipping.
Commit 6: claim checking endpoint. Each claim is pre-checked by the
decision layer against its cited passages; clear cases ship or are
cut, borderline cases escalate to the checker model, and anything
the checker cannot settle comes back "uncertain" rather than
guessed.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.checking import claim_checker_from_settings, split_claims
from app.config import load_settings
from app.decision import DecisionService
from app.drafting import (
    Claim,
    DraftResult,
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


class CheckRequest(BaseModel):
    question: str = ""
    answer: str = ""
    claims: list[ClaimOut] = []
    passages: list[PassageIn]


class ClaimVerdictOut(BaseModel):
    text: str
    citations: list[str]
    precheck_probability: float | None
    precheck_backend: str | None
    route: str
    verdict: str
    checked_by: str
    reason: str


class CheckSummary(BaseModel):
    total: int
    supported: int
    unsupported: int
    uncertain: int
    escalated: int


class CheckOut(BaseModel):
    question: str
    claims: list[ClaimVerdictOut]
    summary: CheckSummary


@app.post("/check", response_model=CheckOut)
def check(request: CheckRequest) -> CheckOut:
    passages = [
        Passage(id=p.id, source=p.source, text=p.text) for p in request.passages
    ]
    if request.claims:
        claims = [
            Claim(text=c.text, citations=c.citations) for c in request.claims
        ]
    else:
        # Plain-text answer: split it into claims. They carry no
        # citations, so each one escalates to the checker with all
        # supplied passages as context; none ships on a pre-check.
        claims = [
            Claim(text=text, citations=[]) for text in split_claims(request.answer)
        ]
    draft = DraftResult(
        question=request.question, answer=request.answer,
        claims=claims, model="",
    )
    checked = claim_checker_from_settings(settings).check_draft(draft, passages)
    verdicts = [
        ClaimVerdictOut(
            text=v.text,
            citations=v.citations,
            precheck_probability=v.precheck_probability,
            precheck_backend=v.precheck_backend,
            route=v.route,
            verdict=v.verdict,
            checked_by=v.checked_by,
            reason=v.reason,
        )
        for v in checked.verdicts
    ]
    summary = CheckSummary(
        total=len(verdicts),
        supported=sum(1 for v in verdicts if v.verdict == "supported"),
        unsupported=sum(1 for v in verdicts if v.verdict == "unsupported"),
        uncertain=sum(1 for v in verdicts if v.verdict == "uncertain"),
        escalated=sum(1 for v in verdicts if v.route == "escalated"),
    )
    return CheckOut(question=request.question, claims=verdicts, summary=summary)
