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
    """Configured primary backend first, rules on any failure. One
    triage call can carry several questions (build pack: intake
    triage per question, one call, several questions)."""

    def __init__(self, settings: Settings, timeout: float = 10.0) -> None:
        self._primary = _triage_backend(settings, timeout)
        self._fallback = RulesDecisionBackend()

    def triage(self, questions: list[str]) -> list[TriageResult]:
        results = []
        for question in questions:
            try:
                results.append(self._primary.triage(question))
            except DecisionError:
                results.append(self._fallback.triage(question))
        return results


# ------------------------------------------------------------------
# Claim-support pre-check (commit 6). Second decision task from the
# build pack: per drafted claim, a probability that the cited
# passage supports the claim. Same sidecar, second task name:
#
#     POST {decision_base_url}/decide
#     {"model": ..., "task": "claim-support",
#      "input": {"claim": str, "passage": str}}
#     -> {"supported": bool, "probability": float 0..1}
#
# The routing bands live in app/checking.py, not here: this layer
# only produces the probability and names its backend.
# ------------------------------------------------------------------

import re

_STOPWORDS = frozenset(
    "the a an and or of to in is are we our you your it its for on "
    "with as at by be this that from have has do does".split()
)


@dataclass(frozen=True)
class ClaimSupportResult:
    claim: str
    supported: bool
    probability: float
    backend: str  # "d3" or "rules"


def _significant_tokens(text: str) -> set[str]:
    return {
        tok
        for tok in re.findall(r"[a-z0-9][a-z0-9\-]*", text.lower())
        if len(tok) > 2 and tok not in _STOPWORDS
    }


class RulesClaimSupportBackend:
    """Deterministic fallback: lexical overlap between the claim and
    the passage. The probability is the share of the claim's
    significant tokens that also appear in the passage. Crude, and
    named as rules wherever it is used — it is a pre-check, not a
    judgement; borderline cases escalate to the checker model."""

    name = "rules"

    def claim_support(self, claim: str, passage: str) -> ClaimSupportResult:
        claim_tokens = _significant_tokens(claim)
        if not claim_tokens:
            return ClaimSupportResult(
                claim=claim, supported=False, probability=0.0,
                backend=self.name,
            )
        passage_tokens = _significant_tokens(passage)
        probability = len(claim_tokens & passage_tokens) / len(claim_tokens)
        return ClaimSupportResult(
            claim=claim,
            supported=probability >= 0.5,
            probability=round(probability, 4),
            backend=self.name,
        )


class HTTPClaimSupportBackend:
    """Calls the d3-lite sidecar for claim support; raises
    DecisionError on any failure so the service can fall back."""

    name = "d3"

    def __init__(self, settings: Settings, timeout: float = 10.0) -> None:
        self._base = settings.decision_base_url.rstrip("/")
        self._model = settings.decision_model
        self._timeout = timeout

    def claim_support(self, claim: str, passage: str) -> ClaimSupportResult:
        payload = {
            "model": self._model,
            "task": "claim-support",
            "input": {"claim": claim, "passage": passage},
        }
        try:
            resp = httpx.post(
                f"{self._base}/decide",
                json=payload,
                timeout=self._timeout,
                trust_env=False,
            )
            resp.raise_for_status()
            data = resp.json()
            supported = bool(data["supported"])
            probability = float(data["probability"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise DecisionError(f"d3 claim-support call failed: {exc}") from exc
        if not 0.0 <= probability <= 1.0:
            raise DecisionError("d3 claim-support probability outside 0..1")
        return ClaimSupportResult(
            claim=claim, supported=supported, probability=probability,
            backend=self.name,
        )


class ClaimSupportService:
    """Configured primary backend first, rules on any failure — same
    discipline as triage."""

    def __init__(self, settings: Settings, timeout: float = 10.0) -> None:
        self._primary = _claim_support_backend(settings, timeout)
        self._fallback = RulesClaimSupportBackend()

    def claim_support(self, claim: str, passage: str) -> ClaimSupportResult:
        try:
            return self._primary.claim_support(claim, passage)
        except DecisionError:
            return self._fallback.claim_support(claim, passage)


# ------------------------------------------------------------------
# LLM decision backend (option A, hackathon submission build). The
# decision tasks are served by a chat model on the same
# OpenAI-compatible endpoint as drafting/checking — for the AMD
# hackathon that is DeepSeek-V4.1-Flash on AMD Token Factory — asked
# for JSON only and parsed strictly. Any transport error, malformed
# JSON, unknown category, or out-of-range score raises DecisionError
# and the services above fall back to rules, with the backend named
# in every result. Selected with DECISION_BACKEND=llm; the d3
# sidecar ("d3") stays the default for the self-hosted build.
# ------------------------------------------------------------------

import json

from app.vllm_client import VLLMClient, VLLMError

_CATEGORIES = [label for label, _ in _CATEGORY_KEYWORDS] + ["general"]

_TRIAGE_SYSTEM = (
    "You are the decision layer for a security-questionnaire desk. "
    "Classify the question and score it. Return JSON only, no prose: "
    '{"category": one of ' + json.dumps(_CATEGORIES) + ', '
    '"sensitivity": number 0..1 (how sensitive answering it is), '
    '"answerable": number 0..1 (how likely a typical company policy '
    "library can answer it)}"
)

_CLAIM_SUPPORT_SYSTEM = (
    "You are the decision layer for a security-questionnaire desk. "
    "Judge whether the passage supports the claim. Return JSON only, "
    'no prose: {"supported": true or false, "probability": number '
    "0..1 (probability the passage supports the claim)}"
)


def _parse_json_object(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise DecisionError("decision model returned no JSON object")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise DecisionError(f"decision model returned bad JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise DecisionError("decision model returned a non-object JSON")
    return data


def _score(data: dict, field: str) -> float:
    try:
        value = float(data[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise DecisionError(f"decision model reply missing {field}") from exc
    if not 0.0 <= value <= 1.0:
        raise DecisionError(f"decision model {field} outside 0..1")
    return value


class LLMTriageBackend:
    name = "llm"

    def __init__(self, settings: Settings, timeout: float = 30.0) -> None:
        self._client = VLLMClient(settings, timeout=timeout)
        self._model = settings.decision_model

    def triage(self, question: str) -> TriageResult:
        try:
            text = self._client.chat(
                self._model,
                [
                    {"role": "system", "content": _TRIAGE_SYSTEM},
                    {"role": "user", "content": question},
                ],
                temperature=0.0,
                max_tokens=256,
            )
        except VLLMError as exc:
            raise DecisionError(f"llm triage call failed: {exc}") from exc
        data = _parse_json_object(text)
        category = str(data.get("category", ""))
        if category not in _CATEGORIES:
            raise DecisionError(f"llm triage returned unknown category {category!r}")
        return TriageResult(
            question=question,
            category=category,
            sensitivity=_score(data, "sensitivity"),
            answerable=_score(data, "answerable"),
            backend=self.name,
        )


class LLMClaimSupportBackend:
    name = "llm"

    def __init__(self, settings: Settings, timeout: float = 30.0) -> None:
        self._client = VLLMClient(settings, timeout=timeout)
        self._model = settings.decision_model

    def claim_support(self, claim: str, passage: str) -> ClaimSupportResult:
        prompt = f"Claim: {claim}\n\nPassage: {passage}"
        try:
            text = self._client.chat(
                self._model,
                [
                    {"role": "system", "content": _CLAIM_SUPPORT_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=256,
            )
        except VLLMError as exc:
            raise DecisionError(f"llm claim-support call failed: {exc}") from exc
        data = _parse_json_object(text)
        return ClaimSupportResult(
            claim=claim,
            supported=bool(data.get("supported")),
            probability=_score(data, "probability"),
            backend=self.name,
        )


def _triage_backend(settings: Settings, timeout: float):
    if settings.decision_backend == "llm":
        return LLMTriageBackend(settings, timeout=max(timeout, 30.0))
    if settings.decision_backend == "rules":
        return RulesDecisionBackend()
    return HTTPDecisionBackend(settings, timeout=timeout)


def _claim_support_backend(settings: Settings, timeout: float):
    if settings.decision_backend == "llm":
        return LLMClaimSupportBackend(settings, timeout=max(timeout, 30.0))
    if settings.decision_backend == "rules":
        return RulesClaimSupportBackend()
    return HTTPClaimSupportBackend(settings, timeout=timeout)
