"""Retrieval: BM25 over the document corpus.

Until now the caller hand-bundled the passages for every question
(the sample pack's per-question source document, or the whole
library). This module is the missing retrieval step the drafting
contract always assumed: given a question, rank the corpus and
return the passages most likely to carry its answer.

Dependency-free Okapi BM25 (k1=1.5, b=0.75) over the same
significant-token rules as the lexical claim-support fallback in
app/decision.py: lowercase alphanumeric tokens (hyphens kept, so
part numbers like aes-256 stay one token), length over 2, English
stopwords dropped. Passage ids are the corpus's own stable ids
(the sample pack's "{doc-stem}-{paragraph}" ids), so a retrieved
passage cites exactly like a hand-supplied one.

Ranking is deterministic: score descending, passage id ascending
on ties. A query sharing no significant token with a passage
scores it 0, and zero-score passages are never returned — a
question nothing in the corpus speaks to retrieves nothing, and
the pipeline hands it off instead of drafting from noise.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

from app.drafting import Passage

_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-]*")

_STOPWORDS = frozenset(
    "the a an and or of to in is are we our you your it its for on "
    "with as at by be this that from have has do does".split()
)

_K1 = 1.5
_B = 0.75
DEFAULT_K = 8


def tokenise(text: str) -> list[str]:
    """Significant tokens of a text, with repetitions (BM25 needs
    term frequencies; the set form lives in app/decision.py)."""
    return [
        tok
        for tok in _TOKEN.findall(text.lower())
        if len(tok) > 2 and tok not in _STOPWORDS
    ]


class BM25Index:
    """Okapi BM25 over a fixed passage list."""

    def __init__(self, passages: list[Passage]) -> None:
        self._passages = list(passages)
        self._tokens = {p.id: tokenise(p.text) for p in self._passages}
        self._tf = {pid: Counter(toks) for pid, toks in self._tokens.items()}
        n = len(self._passages)
        self._avgdl = (
            sum(len(t) for t in self._tokens.values()) / n if n else 0.0
        )
        df = Counter()
        for toks in self._tokens.values():
            df.update(set(toks))
        # Robertson idf, floored at 0: a term in over half the corpus
        # carries no ranking signal.
        self._idf = {
            term: max(0.0, math.log(1 + (n - count + 0.5) / (count + 0.5)))
            for term, count in df.items()
        }

    def score(self, query_tokens: list[str], passage: Passage) -> float:
        tf = self._tf.get(passage.id)
        if tf is None:
            tf = Counter(tokenise(passage.text))
        dl = sum(tf.values())
        denom_norm = _K1 * (1 - _B + _B * (dl / self._avgdl if self._avgdl else 1.0))
        total = 0.0
        for term in set(query_tokens):
            f = tf.get(term, 0)
            if f:
                total += self._idf.get(term, 0.0) * (f * (_K1 + 1)) / (f + denom_norm)
        return total

    def rank(self, query: str) -> list[tuple[Passage, float]]:
        query_tokens = tokenise(query)
        if not query_tokens:
            return []
        scored = [
            (p, self.score(query_tokens, p)) for p in self._passages
        ]
        scored = [pair for pair in scored if pair[1] > 0]
        scored.sort(key=lambda pair: (-pair[1], pair[0].id))
        return scored


class Retriever:
    """A BM25 index over one corpus, with the corpus fingerprint
    the caches key on (stage 3): the same question against a
    different document set must never reuse a result."""

    def __init__(self, passages: list[Passage]) -> None:
        self._passages = list(passages)
        self._by_id = {p.id: p for p in self._passages}
        self._index = BM25Index(self._passages)
        canonical = "\n".join(
            f"{p.id}\x00{p.text}"
            for p in sorted(self._passages, key=lambda p: p.id)
        )
        self.corpus_hash = hashlib.sha256(canonical.encode()).hexdigest()

    def __contains__(self, passage_id: str) -> bool:
        return passage_id in self._by_id

    def passage(self, passage_id: str) -> Passage | None:
        return self._by_id.get(passage_id)

    def retrieve(self, question: str, k: int = DEFAULT_K) -> list[Passage]:
        return [p for p, _ in self._index.rank(question)[:k]]

    def rank(self, text: str) -> list[tuple[Passage, float]]:
        return self._index.rank(text)

    def top_match(self, text: str) -> Passage | None:
        ranked = self._index.rank(text)
        return ranked[0][0] if ranked else None

    def score_against(self, text: str, passage: Passage) -> float:
        """BM25 score of a text (a claim) against one passage, on
        this corpus's idf — the retrieval-aware feature the local
        pre-check (stage 2) combines with lexical overlap."""
        return self._index.score(tokenise(text), passage)
