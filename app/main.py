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
Commit 7: questionnaire endpoint builds the answer sheet (only
supported claims ship, every claim leaves an evidence trail), and
the review queue endpoint lists everything a human still has to
decide. The sheet is held in memory; building a new one replaces it.
Commit 8: Evolus dispatch endpoint sends the finished sheet to the
configured Evolus workflow through the Evolus REST API.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

_STATIC_DIR = Path(__file__).resolve().parent / "static"

from app.answers import (
    AnswerSheet,
    QuestionItem,
    AnswerSheetService,
    render_markdown,
    review_queue,
)
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
from app.evolus import EvolusError, evolus_client_from_settings
from app.sample import sample_items
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


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    client = VLLMClient(settings, timeout=3.0)
    probe = client.probe()
    # Quota is advisory: endpoints that report usage (Token Factory)
    # fill it in, everywhere else it stays null and nothing locks.
    # A failed usage fetch must never fail the health check itself.
    quota = None
    if probe["reachable"]:
        try:
            quota = client.usage()
        except VLLMError:
            quota = None
    return {
        "status": "ok",
        "drafter_model": settings.drafter_model,
        "checker_model": settings.checker_model,
        "decision_model": settings.decision_model,
        "vllm": probe,
        "quota": quota,
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


class QuestionnaireItemIn(BaseModel):
    question: str
    passages: list[PassageIn]


class QuestionnaireRequest(BaseModel):
    items: list[QuestionnaireItemIn]


class EvidenceOut(BaseModel):
    claim: str
    verdict: str
    citations: list[str]
    sources: list[str]
    checked_by: str
    precheck_probability: float | None
    reason: str


class AnswerEntryOut(BaseModel):
    question: str
    status: str
    shipped_answer: str
    evidence_trail: list[EvidenceOut]
    flags: list[str]


class AnswerSheetOut(BaseModel):
    entries: list[AnswerEntryOut]
    counts: dict
    markdown: str


class ReviewItemOut(BaseModel):
    question: str
    status: str
    reasons: list[str]
    blocked_claims: list[EvidenceOut]


def _sheet_out(sheet: AnswerSheet) -> AnswerSheetOut:
    return AnswerSheetOut(
        entries=[
            AnswerEntryOut(
                question=e.question,
                status=e.status,
                shipped_answer=e.shipped_answer,
                evidence_trail=[
                    EvidenceOut(
                        claim=t.claim, verdict=t.verdict,
                        citations=t.citations, sources=t.sources,
                        checked_by=t.checked_by,
                        precheck_probability=t.precheck_probability,
                        reason=t.reason,
                    )
                    for t in e.evidence_trail
                ],
                flags=e.flags,
            )
            for e in sheet.entries
        ],
        counts=sheet.counts,
        markdown=render_markdown(sheet),
    )


def _stored_sheet() -> AnswerSheet:
    sheet = getattr(app.state, "answer_sheet", None)
    if sheet is None:
        raise HTTPException(
            status_code=404,
            detail="no answer sheet built yet; POST /questionnaire first",
        )
    return sheet


@app.get("/sample", response_model=QuestionnaireRequest)
def sample() -> QuestionnaireRequest:
    """The demo pack (fictional KiteMetric): the labelled sample
    questionnaire with its document passages, ready to POST back to
    /questionnaire. Expected labels stay server-side."""
    return QuestionnaireRequest(
        items=[
            QuestionnaireItemIn(
                question=item.question,
                passages=[
                    PassageIn(id=p.id, source=p.source, text=p.text)
                    for p in item.passages
                ],
            )
            for item in sample_items()
        ]
    )


@app.post("/questionnaire", response_model=AnswerSheetOut)
def questionnaire(
    request: QuestionnaireRequest, append: bool = False
) -> AnswerSheetOut:
    """Build the answer sheet for the given questions. With
    ?append=true the new entries extend the stored sheet instead of
    replacing it, so a client can run questions one at a time (the
    demo UI does this: progress per question, and no single request
    has to outlive a serverless time limit)."""
    service = AnswerSheetService(
        drafting=drafting_service_from_settings(settings),
        checker=claim_checker_from_settings(settings),
    )
    items = [
        QuestionItem(
            question=item.question,
            passages=[
                Passage(id=p.id, source=p.source, text=p.text)
                for p in item.passages
            ],
        )
        for item in request.items
    ]
    try:
        sheet = service.build(items)
    except (DraftingError, VLLMError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if append:
        existing = getattr(app.state, "answer_sheet", None)
        if existing is not None:
            sheet = AnswerSheet(entries=[*existing.entries, *sheet.entries])
    app.state.answer_sheet = sheet
    return _sheet_out(sheet)


@app.get("/answers", response_model=AnswerSheetOut)
def answers() -> AnswerSheetOut:
    return _sheet_out(_stored_sheet())


class EvolusDispatchOut(BaseModel):
    workflow_id: str
    execution: dict


@app.post("/evolus/dispatch", response_model=EvolusDispatchOut)
def evolus_dispatch() -> EvolusDispatchOut:
    """Send the current answer sheet to the configured Evolus
    workflow, where the business process continues (human review,
    filing, notification). 503 when Evolus is not configured, 502
    when the Evolus call itself fails."""
    settings = load_settings()
    client = evolus_client_from_settings(settings)
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Evolus is not configured (EVOLUS_API_KEY / "
                   "EVOLUS_APPLICATION_ID missing)",
        )
    sheet = _stored_sheet()
    try:
        execution = client.execute_workflow(
            settings.evolus_workflow_id,
            {"answer_sheet": render_markdown(sheet)},
        )
    except EvolusError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return EvolusDispatchOut(
        workflow_id=settings.evolus_workflow_id, execution=execution
    )


@app.get("/review-queue", response_model=list[ReviewItemOut])
def review() -> list[ReviewItemOut]:
    return [
        ReviewItemOut(
            question=item.question,
            status=item.status,
            reasons=item.reasons,
            blocked_claims=[
                EvidenceOut(
                    claim=t.claim, verdict=t.verdict,
                    citations=t.citations, sources=t.sources,
                    checked_by=t.checked_by,
                    precheck_probability=t.precheck_probability,
                    reason=t.reason,
                )
                for t in item.blocked_claims
            ],
        )
        for item in review_queue(_stored_sheet())
    ]
