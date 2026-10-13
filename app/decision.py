"""Decision layer wrapper: intake triage for incoming questions.

Commit 3: a DecisionService in front of the d3-lite decision model,
with the routing-rules fallback the build plan already names for the
case where d3-lite cannot run (new transformers pin on ROCm). The
service contract for the future d3 sidecar is one call:

    POST {decision_base_url}/decide
    {"model": ..., "task": "triage", "input": <question>}
    -> {"category": str, "sensitivity": float 0..1,
        "answerable": float 0..1}

Any transport error, bad status, or malformed reply falls back to
the deterministic rules backend, and every result reports which
backend produced it — a rules answer is never dressed up as a model
answer. The rules backend cannot judge whether the document library
can answer a question, so it returns answerable=None rather than
inventing a score.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import Settings


class DecisionError(RuntimeError):
    pass


@dataclass(frozen=True)
class TriageResult:
    question: str
    category: str
    sensitivity: float
    answerable: float | None
    backend: str  # "d3" or "rules"


# Category is a choice over a fixed label set; keyword hits decide.
_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("access-control", ("access control", "mfa", "multi-factor", "sso",
                        "single sign-on", "authentication", "password",
                        "privileged", "least privilege")),
    ("encryption", ("encrypt", "tls", "at rest", "in transit", "key management",
                    "cryptograph")),
    ("data-retention", ("retention", "delete", "deletion", "backup", "archive",
                        "data lifecycle")),
    ("incident-response", ("incident", "breach", "response plan", "notification",
                           "disaster recovery", "business continuity")),
    ("privacy", ("personal data", "gdpr", "privacy", "consent", "data subject",
                 "pii", "cross-border")),
    ("compliance", ("soc 2", "iso 27001", "certif", "audit", "compliance",
                    "penetration test", "pen test", "vulnerability")),
    ("subprocessors", ("subprocessor", "sub-processor", "third party",
                       "third-party", "vendor", "hosting provider")),
    ("availability", ("uptime", "sla", "availability", "service level",
                      "maintenance window")),
]

# Sensitivity is a score: weighted hits, capped at 1.0.
_SENSITIVITY_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("credential", 0.4), ("password", 0.3), ("secret", 0.4),
    ("encryption key", 0.4), ("personal data", 0.3), ("pii", 0.3),
    ("breach", 0.3), ("vulnerabilit", 0.2), ("penetration", 0.2),
    ("privileged", 0.2), ("production", 0.15), ("customer data", 0.25),
)


def _score_from_keywords(text: str, weighted: tuple[tuple[str, float], ...]) -> float:
    score = 0.0
    for keyword, weight in weighted:
        if keyword in text:
            score += weight
    return min(score, 1.0)


class RulesDecisionBackend:
    """Deterministic fallback: category by keyword, sensitivity by
    weighted keyword score, answerable unknown (None)."""

    name = "rules"

    def triage(self, question: str) -> TriageResult:
        text = question.lower()
        category = "general"
        best_hits = 0
        for label, keywords in _CATEGORY_KEYWORDS:
            hits = sum(1 for kw in keywords if kw in text)
            if hits > best_hits:
                best_hits = hits
                category = label
        return TriageResult(
            question=question,
            category=category,
            sensitivity=_score_from_keywords(text, _SENSITIVITY_WEIGHTS),
            answerable=None,
            backend=self.name,
        )


class HTTPDecisionBackend:
    """Calls the d3-lite sidecar; raises DecisionError on any failure
    so the service can fall back to rules."""

    name = "d3"

    def __init__(self, settings: Settings, timeout: float = 10.0) -> None:
        self._base = settings.decision_base_url.rstrip("/")
        self._model = settings.decision_model
        self._timeout = timeout

    def triage(self, question: str) -> TriageResult:
        payload = {"model": self._model, "task": "triage", "input": question}
        try:
            # trust_env=False: droplet traffic is direct infrastructure
            # traffic and must never be routed through an env proxy.
            resp = httpx.post(
                f"{self._base}/decide",
                json=payload,
                timeout=self._timeout,
                trust_env=False,
            )
            resp.raise_for_status()
            data = resp.json()
            category = str(data["category"])
            sensitivity = float(data["sensitivity"])
            answerable = float(data["answerable"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise DecisionError(f"d3 triage call failed: {exc}") from exc
        if not (0.0 <= sensitivity <= 1.0 and 0.0 <= answerable <= 1.0):
            raise DecisionError("d3 triage returned scores outside 0..1")
        return TriageResult(
            question=question,
            category=category,
            sensitivity=sensitivity,
            answerable=answerable,
            backend=self.name,
        )


class DecisionService:
    """d3 first, rules on any failure. One triage call can carry
    several questions (build pack: intake triage per question, one
    call, several questions)."""

    def __init__(self, settings: Settings, timeout: float = 10.0) -> None:
        self._primary = HTTPDecisionBackend(settings, timeout=timeout)
        self._fallback = RulesDecisionBackend()

    def triage(self, questions: list[str]) -> list[TriageResult]:
        results = []
        for question in questions:
            try:
                results.append(self._primary.triage(question))
            except DecisionError:
                results.append(self._fallback.triage(question))
        return results
