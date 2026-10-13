"""Drafting pipeline: the drafter model writes an answer with
citations, from supplied passages only.

Commit 5. The contract that makes the later claim-checking possible:

- The caller supplies the passages (retrieval is a separate step).
  The drafter may use nothing else.
- The drafter must reply with JSON only:
      {"answer": str,
       "claims": [{"text": str, "citations": [passage_id, ...]}]}
- Every citation must name one of the supplied passage ids. A
  citation pointing anywhere else is rejected outright: an answer
  whose evidence cannot be traced is not shipped, it fails here.
- Malformed output raises DraftingError. Nothing is repaired by
  guessing, and no claim is ever invented on this side of the wire.
- With no passages, there is no draft: an empty result, honestly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.vllm_client import VLLMClient, VLLMError

_SYSTEM_PROMPT = (
    "You draft answers to security and compliance questionnaire "
    "questions using ONLY the passages provided. Never use outside "
    "knowledge. Reply with JSON only, no prose around it: "
    '{"answer": "<the answer text>", "claims": [{"text": "<one '
    'factual claim from the answer>", "citations": ["<passage id>"]}]}. '
    "Every factual claim in the answer must appear in claims with at "
    "least one citation naming a passage id exactly as given. If the "
    "passages do not answer the question, reply "
    '{"answer": "", "claims": []}.'
)


class DraftingError(RuntimeError):
    pass


@dataclass(frozen=True)
class Passage:
    id: str
    source: str
    text: str


@dataclass(frozen=True)
class Claim:
    text: str
    citations: list[str]


@dataclass(frozen=True)
class DraftResult:
    question: str
    answer: str
    claims: list[Claim]
    model: str


def build_messages(question: str, passages: list[Passage]) -> list[dict]:
    blocks = "\n\n".join(
        f"[{p.id}] (source: {p.source})\n{p.text}" for p in passages
    )
    user = f"Question: {question}\n\nPassages:\n{blocks}"
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


class DraftingService:
    """One drafting call. The client is anything with a
    chat(model, messages, ...) method returning text: VLLMClient in
    production, a fake in tests."""

    def __init__(self, client, model: str) -> None:
        self._client = client
        self._model = model

    def draft(self, question: str, passages: list[Passage]) -> DraftResult:
        if not passages:
            return DraftResult(
                question=question, answer="", claims=[], model=self._model
            )
        try:
            raw = self._client.chat(
                self._model,
                build_messages(question, passages),
                temperature=0.2,
                max_tokens=1024,
            )
        except VLLMError as exc:
            raise DraftingError(f"drafter call failed: {exc}") from exc
        return self._parse(question, raw, passages)

    def _parse(
        self, question: str, raw: str, passages: list[Passage]
    ) -> DraftResult:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            data = json.loads(text)
            answer = str(data["answer"])
            raw_claims = data["claims"]
            claims = []
            for item in raw_claims:
                citations = [str(c) for c in item["citations"]]
                claims.append(Claim(text=str(item["text"]), citations=citations))
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
            raise DraftingError(f"drafter returned malformed output: {exc}") from exc
        known = {p.id for p in passages}
        for claim in claims:
            if not claim.citations:
                raise DraftingError(
                    f"claim has no citation: {claim.text[:60]!r}"
                )
            unknown = [c for c in claim.citations if c not in known]
            if unknown:
                raise DraftingError(
                    f"claim cites unknown passages {unknown}: "
                    f"{claim.text[:60]!r}"
                )
        return DraftResult(
            question=question, answer=answer, claims=claims, model=self._model
        )


def drafting_service_from_settings(settings) -> DraftingService:
    return DraftingService(
        VLLMClient(settings), model=settings.drafter_model
    )
