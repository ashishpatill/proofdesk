"""In-process content-hash caches (stage 3).

Repeated runs of the same questionnaire over the same documents
repeat the same retrieval and the same claim judgements. Those
results are deterministic functions of their content, so they are
cached in-process, keyed on content hashes:

- (corpus version hash, question) -> ranked passage ids
- (claim text, passage ids, verifier identity) -> claim-support result

Because the document content itself is inside every key, a
different document set can never be served a result computed
against another one — there is no invalidation problem to solve,
only a key to compute. The caches are process-local and
deliberately small-minded: no TTL, no persistence, no sharing
across serverless instances, no external cache service. Counters
are kept so a run can report how much work the cache saved.

Two rules the key construction exists to enforce:

1. Retrieval keys on the corpus version hash, so a question asked
   against one document library can never reuse passages chosen for
   another.
2. Verdict keys are EXACT. The claim text is hashed as written —
   no lowercasing, no stripping, no normalisation, no token
   overlap. "Data is encrypted at rest." and "Data is encrypted at
   rest" are different claims and get different keys, because a
   near-duplicate served the verdict of its twin is a false
   approval. A fuzzy verdict cache would be a correctness bug
   wearing a performance hat, and there is none here.

Nothing in this module imports the rest of the app: passages are
anything with ``.id`` and ``.text``.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable


@runtime_checkable
class PassageLike(Protocol):
    """What a cache key needs from a passage. app.drafting.Passage
    satisfies it; so does anything else with an id and a text."""

    id: str
    text: str


def content_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def corpus_version_hash(passages: Sequence[PassageLike]) -> str:
    """The corpus fingerprint: the hash of the sorted per-document
    content hashes.

    Sorting the per-document hashes (rather than the documents) makes
    the fingerprint independent of the order the corpus was loaded in,
    so the same library assembled two ways is one cache entry.

    Each document's own hash covers its id as well as its text. The id
    is not decoration: retrieval results ARE passage ids, so two
    corpora carrying identical text under different ids would hand
    back the wrong ids from a shared entry.
    """
    document_hashes = sorted(
        content_hash(p.id, p.text) for p in passages
    )
    return content_hash("corpus-v1", *document_hashes)


class ContentCache:
    """A thread-safe dict behind content-hash keys, with
    hit/miss counters for reporting."""

    def __init__(self) -> None:
        self._store: dict[str, object] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str):
        with self._lock:
            if key in self._store:
                self.hits += 1
                return self._store[key]
            self.misses += 1
            return None

    def put(self, key: str, value) -> None:
        with self._lock:
            self._store[key] = value

    def stats(self) -> dict:
        with self._lock:
            return {
                "entries": len(self._store),
                "hits": self.hits,
                "misses": self.misses,
            }

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self.hits = 0
            self.misses = 0


class RetrievalCache:
    """Question + corpus version -> the ranked passage ids.

    The WHOLE ranking is stored and the top-k slice is taken on
    read. That keeps the key exactly (question, corpus version) as
    specified while serving every k from one entry, so a different k
    is a slice of the same result rather than a different one.
    """

    def __init__(self) -> None:
        self._cache = ContentCache()

    def key(self, question: str, corpus_version: str) -> str:
        return content_hash("retrieval-v1", question, corpus_version)

    def get_ids(
        self, question: str, corpus_version: str
    ) -> list[str] | None:
        """The cached ranking, or None on a miss. An empty list is a
        hit that retrieved nothing — a real result, not a miss."""
        return self._cache.get(self.key(question, corpus_version))

    def put_ids(
        self, question: str, corpus_version: str, passage_ids: Sequence[str]
    ) -> None:
        self._cache.put(
            self.key(question, corpus_version), list(passage_ids)
        )

    def stats(self) -> dict:
        return self._cache.stats()

    def clear(self) -> None:
        self._cache.clear()


class VerdictCache:
    """Exact claim text + cited passages + verifier identity -> the
    claim-support result that verifier returned.

    Exact means exact. The claim goes into the key as written, and
    so does each cited passage's id and text. Only a claim the
    verifier saw verbatim can ever find its entry; anything else
    misses and is asked again.
    """

    def __init__(self) -> None:
        self._cache = ContentCache()

    def key(
        self,
        claim: str,
        passages: Sequence[PassageLike],
        verifier_identity: str,
    ) -> str:
        parts = ["verdict-v1", verifier_identity, claim]
        for passage in passages:
            parts.append(passage.id)
            parts.append(passage.text)
        return content_hash(*parts)

    def get(self, key: str):
        return self._cache.get(key)

    def put(self, key: str, result) -> None:
        self._cache.put(key, result)

    def stats(self) -> dict:
        return self._cache.stats()

    def clear(self) -> None:
        self._cache.clear()


@dataclass
class Caches:
    """The pair of caches plus the switch that turns them off.

    ``enabled = False`` is the eval bypass: callers ask their cache
    for nothing and compute the real answer, so a run sees exactly
    what a cold process sees.
    """

    retrieval: RetrievalCache = field(default_factory=RetrievalCache)
    verdicts: VerdictCache = field(default_factory=VerdictCache)
    enabled: bool = True

    def stats(self) -> dict:
        return {
            "enabled": self.enabled,
            "retrieval": self.retrieval.stats(),
            "verdicts": self.verdicts.stats(),
        }

    def clear(self) -> None:
        self.retrieval.clear()
        self.verdicts.clear()


# The process-wide pair. Library code (tests, the retriever used
# directly) takes this unless it was handed its own; the factories
# that know the settings build their own instead.
DEFAULT_CACHES = Caches()


def caches_from_settings(settings) -> Caches:
    """A cache pair honouring the settings' bypass flag."""
    return Caches(enabled=bool(getattr(settings, "cache_enabled", True)))


def set_cache_enabled(enabled: bool) -> None:
    """Apply the bypass flag to the process-wide caches. Called once
    at app start so the env var reaches retrievers built without an
    explicit cache set."""
    DEFAULT_CACHES.enabled = bool(enabled)


def cache_stats() -> dict:
    return DEFAULT_CACHES.stats()


def clear_caches() -> None:
    DEFAULT_CACHES.clear()