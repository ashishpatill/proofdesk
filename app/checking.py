"""Claim checking: split, pre-check, escalate.

Commit 6. The drafting pipeline (commit 5) produces claims with
citations; this stage decides which of them may ship.

Pipeline per claim:

1. Split — answers that arrive as plain text (a human edit, an
   imported draft) are split into individual claims by
   split_claims(). Structured drafts already carry their claims.
2. Pre-check — the decision layer (app/decision.py, task
   "claim-support") scores P(cited passage supports the claim):
       probability >= 0.80  -> supported, ships
       probability <= 0.30  -> unsupported, cut
       in between           -> borderline, escalates
   A claim with no citations has nothing to pre-check against, so
   it escalates directly, with every supplied passage as context.
3. Escalation — the checker model (32B in production) reads the
   claim and its passages and returns a verdict as JSON only:
       {"verdict": "supported" | "unsupported", "reason": str}
   Malformed output, an unreachable checker, or any other failure
   yields "uncertain" — never a guessed verdict. Uncertain claims
   do not ship; they go to the human review queue (commit 7).

Every verdict records how it was reached: the pre-check probability
and backend, the route taken, and who made the final call.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.decision import ClaimSupportService
from app.drafting import Claim, DraftResult, Passage
from app.vllm_client import VLLMClient, VLLMError

SHIP_AT = 0.80
CUT_AT = 0.30

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def split_claims(answer: str) -> list[str]:
    """Split plain answer text into individual claims, one sentence
    each. Bullet markers are stripped; empty fragments dropped."""
    claims = []
    for line in answer.replace("\r\n", "\n").split("\n"):
        line = line.strip().lstrip("-•* ").strip()
        if not line:
            continue
        for part in _SENTENCE_END.split(line):
            part = part.strip()
            if part:
                claims.append(part)
    return claims


@dataclass(frozen=True)
class ClaimVerdict:
    text: str
    citations: list[str]
    precheck_probability: float | None
    precheck_backend: str | None
    route: str  # "ship" | "cut" | "escalated"
    verdict: str  # "supported" | "unsupported" | "uncertain"
    checked_by: str  # "decision" | "checker"
    reason: str


@dataclass(frozen=True)
class CheckedDraft:
    question: str
    verdicts: list[ClaimVerdict]

    @property
    def shipped_claims(self) -> list[ClaimVerdict]:
        return [v for v in self.verdicts if v.verdict == "supported"]

    @property
    def blocked_claims(self) -> list[ClaimVerdict]:
        return [v for v in self.verdicts if v.verdict != "supported"]


_CHECKER_SYSTEM_PROMPT = (
    "You check whether a passage supports a claim. Use ONLY the "
    "passage provided; never use outside knowledge. Reply with JSON "
    'only, no prose around it: {"verdict": "supported" or '
    '"unsupported", "reason": "<one short sentence>"}. Supported '
    "means the passage directly states or clearly implies the "
    "claim. Anything the passage does not cover is unsupported."
)


class CheckerService:
    """The checker of last resort. The client is anything with a
    chat(model, messages, ...) method returning text: VLLMClient in
    production, a fake in tests. Failures return "uncertain", never
    a guessed verdict."""

    def __init__(self, client, model: str) -> None:
        self._client = client
        self._model = model

    def check(self, claim: str, passages: list[Passage]) -> tuple[str, str]:
        blocks = "\n\n".join(
            f"[{p.id}] (source: {p.source})\n{p.text}" for p in passages
        ) or "(no passages supplied)"
        messages = [
            {"role": "system", "content": _CHECKER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Claim: {claim}\n\nPassages:\n{blocks}"},
        ]
        try:
            raw = self._client.chat(
                self._model, messages, temperature=0.0, max_tokens=256
            )
        except VLLMError as exc:
            return "uncertain", f"checker call failed: {exc}"
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            data = json.loads(text)
            verdict = str(data["verdict"])
            reason = str(data.get("reason", ""))
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            return "uncertain", "checker returned malformed output"
        if verdict not in ("supported", "unsupported"):
            return "uncertain", f"checker returned unknown verdict {verdict!r}"
        return verdict, reason


class ClaimChecker:
    """Orchestrates pre-check and escalation for a draft's claims."""

    def __init__(
        self,
        support: ClaimSupportService,
        checker: CheckerService | None,
    ) -> None:
        self._support = support
        self._checker = checker

    def check_draft(
        self, draft: DraftResult, passages: list[Passage]
    ) -> CheckedDraft:
        by_id = {p.id: p for p in passages}
        verdicts = [self._check_claim(c, by_id, passages) for c in draft.claims]
        return CheckedDraft(question=draft.question, verdicts=verdicts)

    def _check_claim(
        self,
        claim: Claim,
        by_id: dict[str, Passage],
        all_passages: list[Passage],
    ) -> ClaimVerdict:
        cited = [by_id[c] for c in claim.citations if c in by_id]
        if cited:
            passage_text = "\n\n".join(p.text for p in cited)
            pre = self._support.claim_support(claim.text, passage_text)
            if pre.probability >= SHIP_AT:
                return ClaimVerdict(
                    text=claim.text, citations=claim.citations,
                    precheck_probability=pre.probability,
                    precheck_backend=pre.backend,
                    route="ship", verdict="supported",
                    checked_by="decision",
                    reason=f"pre-check probability {pre.probability} >= {SHIP_AT}",
                )
            if pre.probability <= CUT_AT:
                return ClaimVerdict(
                    text=claim.text, citations=claim.citations,
                    precheck_probability=pre.probability,
                    precheck_backend=pre.backend,
                    route="cut", verdict="unsupported",
                    checked_by="decision",
                    reason=f"pre-check probability {pre.probability} <= {CUT_AT}",
                )
            return self._escalate(
                claim, cited,
                precheck_probability=pre.probability,
                precheck_backend=pre.backend,
                why=f"pre-check probability {pre.probability} in the borderline band",
            )
        return self._escalate(
            claim, all_passages,
            precheck_probability=None, precheck_backend=None,
            why="claim has no citations to pre-check against",
        )

    def _escalate(
        self,
        claim: Claim,
        context: list[Passage],
        *,
        precheck_probability: float | None,
        precheck_backend: str | None,
        why: str,
    ) -> ClaimVerdict:
        if self._checker is None:
            verdict, reason = "uncertain", "no checker configured"
        else:
            verdict, reason = self._checker.check(claim.text, context)
        return ClaimVerdict(
            text=claim.text, citations=claim.citations,
            precheck_probability=precheck_probability,
            precheck_backend=precheck_backend,
            route="escalated", verdict=verdict,
            checked_by="checker",
            reason=f"{why}; checker: {reason}" if reason else why,
        )


def claim_checker_from_settings(settings) -> ClaimChecker:
    return ClaimChecker(
        support=ClaimSupportService(settings, timeout=3.0),
        checker=CheckerService(VLLMClient(settings), model=settings.checker_model),
    )
