"""Content cache tests (stage 3, module only — wiring is pinned
separately): identical content hits, differing content can never
collide into a stale result."""

from app.caching import ContentCache, content_hash


def test_hash_is_stable_and_content_sensitive():
    assert content_hash("claim", "passage") == content_hash(
        "claim", "passage"
    )
    assert content_hash("claim", "passage") != content_hash(
        "claim", "passage!"
    )
    # Part boundaries are unambiguous: ("ab", "c") != ("a", "bc").
    assert content_hash("ab", "c") != content_hash("a", "bc")


def test_get_put_and_counters():
    cache = ContentCache()
    key = content_hash("q", "corpus-a")
    assert cache.get(key) is None
    cache.put(key, ["p1", "p2"])
    assert cache.get(key) == ["p1", "p2"]
    stats = cache.stats()
    assert stats == {"entries": 1, "hits": 1, "misses": 1}


def test_different_corpus_never_hits():
    cache = ContentCache()
    cache.put(content_hash("corpus-a", "question"), ["p1"])
    assert cache.get(content_hash("corpus-b", "question")) is None


def test_clear_resets():
    cache = ContentCache()
    cache.put("k", 1)
    cache.get("k")
    cache.clear()
    assert cache.stats() == {"entries": 0, "hits": 0, "misses": 0}
    assert cache.get("k") is None
