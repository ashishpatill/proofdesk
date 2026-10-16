"""Answer sheet and human review queue.

Commit 7. This is where the pipeline's output takes its final
shape: one entry per question, an answer built ONLY from claims
that survived checking, and an evidence trail that lets a human
audit every shipped claim back to its source passage.

Entry status:

- "answered" — a draft existed and every claim shipped.
- "partial" — some claims shipped, some were blocked. The shipped
  answer contains only the supported claims, word for word; the
  blocked ones are listed with their verdicts and reasons.
- "handoff" — nothing ships: either the documents did not answer
  the question (no draft) or every claim was blocked. Handing off
  is the designed behaviour for questions the evidence cannot
  carry, never a failure to hide.

The review queue is every entry that is not cleanly "answered",
each with its reasons. Storage is in-memory and single-process —
this is the demo-scope sheet the API serves; nothing here pretends
to be a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.checking import ClaimChecker, ClaimVerdict
from app.drafting import DraftingError, DraftingService, Passage


@dataclass(frozen=True)
class QuestionItem:
    question: str
    passages: list[Passage]


@dataclass(frozen=True)
class EvidenceItem:
    claim: str
    verdict: str
    citations: list[str]
    sources: list[str]
    checked_by: str
    precheck_probability: float | None
    reason: str


@dataclass(frozen=True)
class AnswerEntry:
    question: str
    status: str  # "answered" | "partial" | "handoff"
    shipped_answer: str
    evidence_trail: list[EvidenceItem]
    flags: list[str]
    # Passage ids the retrieval step supplied for this question
    # (empty when the caller supplied the passages itself): the
    # record of what the drafter was allowed to see.
    retrieved_passages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AnswerSheet:
    entries: list[AnswerEntry]

    @property
    def counts(self) -> dict:
        verdicts = [
            item
            for entry in self.entries
            for item in entry.evidence_trail
        ]
        return {
            "questions": len(self.entries),
            "answered": sum(1 for e in self.entries if e.status == "answered"),
            "partial": sum(1 for e in self.entries if e.status == "partial"),
            "handoff": sum(1 for e in self.entries if e.status == "handoff"),
            "claims_checked": len(verdicts),
            "claims_shipped": sum(
                1 for v in verdicts if v.verdict == "supported"
            ),
            "claims_blocked": sum(
                1 for v in verdicts if v.verdict != "supported"
            ),
            "review_items": len(review_queue(self)),
        }


@dataclass(frozen=True)
class ReviewItem:
    question: str
    status: str
    reasons: list[str]
    blocked_claims: list[EvidenceItem] = field(default_factory=list)


def review_queue(sheet: AnswerSheet) -> list[ReviewItem]:
    """Everything a human still has to decide: partial and handoff
    entries, with the reason for every blocked claim."""
    queue = []
    for entry in sheet.entries:
        if entry.status == "answered":
            continue
        blocked = [
            item for item in entry.evidence_trail
            if item.verdict != "supported"
        ]
        queue.append(
            ReviewItem(
                question=entry.question,
                status=entry.status,
                reasons=list(entry.flags),
                blocked_claims=blocked,
            )
        )
    return queue


class AnswerSheetService:
    """Runs draft -> check per question and assembles the sheet.
    Both services are injected, so tests drive the whole pipeline
    with fakes."""

    def __init__(
        self,
        drafting: DraftingService,
        checker: ClaimChecker,
        retriever=None,
    ) -> None:
        self._drafting = drafting
        self._checker = checker
        self._retriever = retriever

    def build(self, items: list[QuestionItem]) -> AnswerSheet:
        return AnswerSheet(entries=[self._build_one(item) for item in items])

    def _build_one(self, item: QuestionItem) -> AnswerEntry:
        # Supplied passages win; with none supplied and a retriever
        # attached, the retrieval step fills them from the corpus
        # and the entry records which passages it chose.
        passages = item.passages
        retrieved_ids: list[str] = []
        if not passages and self._retriever is not None:
            passages = self._retriever.retrieve(item.question)
            retrieved_ids = [p.id for p in passages]
        try:
            draft = self._drafting.draft(item.question, passages)
        except DraftingError as exc:
            # One failed question must not sink the whole sheet: it
            # becomes a hand-off, with the failure on the record.
            return AnswerEntry(
                question=item.question,
                status="handoff",
                shipped_answer="",
                evidence_trail=[],
                flags=[f"drafting failed ({exc}); handed off to a human"],
                retrieved_passages=retrieved_ids,
            )
        sources = {p.id: p.source for p in passages}
        if not draft.claims:
            return AnswerEntry(
                question=item.question,
                status="handoff",
                shipped_answer="",
                evidence_trail=[],
                flags=[
                    "the supplied documents do not answer this question; "
                    "handed off instead of guessing"
                ],
                retrieved_passages=retrieved_ids,
            )
        checked = self._checker.check_draft(draft, passages)
        trail = [
            EvidenceItem(
                claim=v.text,
                verdict=v.verdict,
                citations=v.citations,
                sources=[sources[c] for c in v.citations if c in sources],
                checked_by=v.checked_by,
                precheck_probability=v.precheck_probability,
                reason=v.reason,
            )
            for v in checked.verdicts
        ]
        shipped = [v for v in checked.verdicts if v.verdict == "supported"]
        blocked: list[ClaimVerdict] = [
            v for v in checked.verdicts if v.verdict != "supported"
        ]
        flags = [
            f"claim blocked ({v.verdict}): {v.text} — {v.reason}"
            for v in blocked
        ]
        if not blocked:
            status = "answered"
        elif shipped:
            status = "partial"
        else:
            status = "handoff"
            flags.append(
                "every claim was blocked; nothing ships for this question"
            )
        return AnswerEntry(
            question=item.question,
            status=status,
            shipped_answer=" ".join(v.text for v in shipped),
            evidence_trail=trail,
            flags=flags,
            retrieved_passages=retrieved_ids,
        )


def render_markdown(sheet: AnswerSheet) -> str:
    counts = sheet.counts
    lines = [
        "# ProofDesk answer sheet",
        "",
        f"Questions: {counts['questions']} "
        f"(answered {counts['answered']}, partial {counts['partial']}, "
        f"handoff {counts['handoff']}) · "
        f"claims checked {counts['claims_checked']}, "
        f"shipped {counts['claims_shipped']}, "
        f"blocked {counts['claims_blocked']}",
        "",
    ]
    for entry in sheet.entries:
        lines.append(f"## {entry.question}")
        lines.append(f"Status: {entry.status}")
        if entry.retrieved_passages:
            lines.append(
                "Retrieved passages: " + ", ".join(entry.retrieved_passages)
            )
        lines.append("")
        if entry.shipped_answer:
            lines.append(entry.shipped_answer)
            lines.append("")
        if entry.evidence_trail:
            lines.append("Evidence trail:")
            for item in entry.evidence_trail:
                sources = ", ".join(item.sources) or "no source"
                lines.append(
                    f"- [{item.verdict}] {item.claim} "
                    f"(checked by {item.checked_by}; sources: {sources})"
                )
            lines.append("")
        if entry.flags:
            lines.append("Needs review:")
            for flag in entry.flags:
                lines.append(f"- {flag}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
