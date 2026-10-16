"""In-process content-hash caches (stage 3).

Repeated runs of the same questionnaire over the same documents
repeat the same retrieval and the same claim judgements. Those
results are deterministic functions of their content, so they are
cached in-process, keyed on content hashes:

- (corpus fingerprint, question) -> retrieved passage ids
- (claim, passage text) -> claim-support result / checker verdict

Because the document content itself is inside every key, a
different document set can never be served a result computed
against another one — there is no invalidation problem to solve,
only a key to compute. The caches are process-local and
deliberately small-minded: no TTL, no persistence, no sharing
across serverless instances. Counters are kept so a run can
report how much work the cache actually saved.
"""

from __future__ import annotations

import hashlib
import threading


def content_hash(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


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
