"""Instant local claim-support pre-check (stage 2).

Most claims in a clean draft are not borderline: the claim restates
its cited passage nearly word for word. Sending those to a hosted
model call (~19s each on the shared endpoint) buys nothing. This
module resolves exactly that one clear case locally, in
microseconds, and defers everything else to the existing model
path untouched (decision pre-check, 0.80/0.30 bands, checker
escalation).

The fast path can only SHIP, never cut. A wrong local cut would
silently kill a true claim — a paraphrase can share zero tokens
with its passage and still be supported — while deferring a cut
costs one model call. The asymmetry decides it: cuts stay with
the models.

Safety discipline, in order:

1. Absence and negative claims NEVER resolve locally. A claim that
   something is not mentioned, not offered, or cannot be done is
   judged by the model path, whose exclusivity rule it carries;
   the local path has no business shipping one.
2. Local verdicts require the cited passages to be passages of
   THIS corpus, text-identical to the corpus copy. Anything else
   (a foreign corpus, a hand-edited passage) defers to the models.
3. Ship requires overwhelming support: every significant token of
   the claim appears in the cited text (lexical overlap 1.0), and
   retrieval independently ranks a cited passage as the top match
   for the claim. Both signals, not either.

A local verdict names its backend "local" wherever it is recorded;
it is never dressed up as a model verdict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.decision import RulesClaimSupportBackend
from app.drafting import Claim, Passage
from app.retrieval import Retriever, tokenise

_ABSENCE = re.compile(
    r"\b(do|does|did)\s+not\b"
    r"|\bnot\s+(mentioned|offered|available|provided|supported|"
    r"published|stated|specified|listed|described|covered)\b"
    r"|\bno\s+other\b"
    r"|\bno\s+mention\b"
    r"|\bnever\b"
    r"|\bcannot\b|\bcan\s*not\b|\b\w+n['’]t\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LocalDecision:
    verdict: str  # always "supported": the fast path never cuts
    probability: float  # 1.0, the overlap it required
    reason: str


class LocalPrecheck:
    """Clear-case resolver in front of the model pre-check."""

    def __init__(self, retriever: Retriever) -> None:
        self._retriever = retriever
        self._rules = RulesClaimSupportBackend()

    def try_decide(
        self, claim: Claim, cited: list[Passage]
    ) -> LocalDecision | None:
        if not cited:
            return None
        if _ABSENCE.search(claim.text):
            return None
        # Corpus guard: local verdicts only on passages this
        # retriever holds, text-identical to the corpus copy.
        for passage in cited:
            held = self._retriever.passage(passage.id)
            if held is None or held.text != passage.text:
                return None
        if not tokenise(claim.text):
            return None
        joined = "\n\n".join(p.text for p in cited)
        overlap = self._rules.claim_support(claim.text, joined).probability
        if overlap < 1.0:
            return None
        top = self._retriever.top_match(claim.text)
        if top is None or not any(top.id == p.id for p in cited):
            return None
        return LocalDecision(
            verdict="supported",
            probability=1.0,
            reason=(
                "local pre-check: every significant token of the "
                "claim appears in the cited passage and retrieval "
                "ranks that passage first for the claim; shipped "
                "without a model call"
            ),
        )
