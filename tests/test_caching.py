"""Stage 3 cache tests.

The caches are an optimisation, so the contract they must never break
is the one that says: on a miss, behave exactly as if there were no
cache. These tests pin that, plus the two failure modes a
content-hash cache is specifically there to prevent:

- retrieval never serves passages chosen for a different corpus;
- the verdict cache is EXACT. A near-duplicate claim must miss and be
  asked again, because a verdict served to a claim it was never
  given is a false approval.
"""

import threading

import pytest

from app.caching import (
    Caches,
    ContentCache,
    RetrievalCache,
    VerdictCache,
    cache_stats,
    caches_from_settings,
    clear_caches,
    content_hash,
    corpus_version_hash,
    set_cache_enabled,
)
from app.checking import ClaimChecker
from app.config import Settings
from app.decision import (
    ClaimSupportResult,
    RulesClaimSupportBackend,
    claim_support_backend_name,
    claim_support_identity,
)
from app.drafting import Claim, DraftResult, Passage
from app.retrieval import Retriever


# ------------------------------------------------------------------
# Primitives
# ------------------------------------------------------------------

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


# ------------------------------------------------------------------
# Corpus version hash
# ------------------------------------------------------------------

P1 = Passage(
    id="security-1",
    source="security-policy.md",
    text="Data is encrypted at rest using AES-256.",
)
P2 = Passage(
    id="compliance-1",
    source="compliance.md",
    text="KiteMetric holds SOC 2 Type I, audited March 2026.",
)
EDITED = Passage(id=P1.id, source=P1.source, text=P1.text + " Also TLS 1.2.")
EDITED_P = Passage(
    id="a-1", source="a.md",
    text="Data is encrypted at rest using AES-256 and AES-128.",
)


def test_corpus_hash_is_stable_across_calls():
    assert corpus_version_hash([P1, P2]) == corpus_version_hash([P1, P2])


def test_corpus_hash_ignores_load_order():
    # The same library assembled two ways is one cache entry.
    assert corpus_version_hash([P1, P2]) == corpus_version_hash([P2, P1])


def test_corpus_hash_changes_when_a_document_is_edited():
    assert corpus_version_hash([P1, P2]) != corpus_version_hash(
        [EDITED, P2]
    )


def test_corpus_hash_changes_when_a_document_is_removed():
    assert corpus_version_hash([P1, P2]) != corpus_version_hash([P1])


def test_corpus_hash_covers_the_passage_id():
    # Retrieval results ARE passage ids: identical text under a
    # different id is a different corpus, not the same one.
    renamed = Passage(id="other-1", source=P1.source, text=P1.text)
    assert corpus_version_hash([P1]) != corpus_version_hash([renamed])


def test_corpus_hash_of_empty_corpus_is_stable():
    assert corpus_version_hash([]) == corpus_version_hash([])


# ------------------------------------------------------------------
# Retrieval cache
# ------------------------------------------------------------------

CORPUS = [
    Passage(id="a-1", source="a.md",
            text="Data is encrypted at rest using AES-256."),
    Passage(id="a-2", source="a.md",
            text="TLS 1.2 is enforced for data in transit."),
    Passage(id="b-1", source="b.md",
            text="KiteMetric holds SOC 2 Type I, audited March 2026."),
]
QUESTION = "How is customer data encrypted at rest?"


def _fresh_retriever(corpus=None) -> Retriever:
    return Retriever(list(corpus or CORPUS), caches=Caches())


def test_repeated_retrieval_hits_the_cache():
    caches = Caches()
    retriever = Retriever(CORPUS, caches=caches)
    first = retriever.retrieve(QUESTION)
    assert caches.retrieval.stats()["misses"] == 1
    second = retriever.retrieve(QUESTION)
    assert caches.retrieval.stats()["hits"] == 1
    assert [p.id for p in second] == [p.id for p in first]


def test_cache_hit_returns_the_same_passage_objects():
    caches = Caches()
    retriever = Retriever(CORPUS, caches=caches)
    first = retriever.retrieve(QUESTION)
    second = retriever.retrieve(QUESTION)
    assert [p.text for p in second] == [p.text for p in first]
    assert all(a.id == b.id for a, b in zip(first, second))


def test_one_entry_serves_every_k():
    # The key is (question, corpus version) only, so a different k
    # must be a slice of the same ranking, never a second entry.
    caches = Caches()
    retriever = Retriever(CORPUS, caches=caches)
    top_one = retriever.retrieve(QUESTION, k=1)
    top_two = retriever.retrieve(QUESTION, k=2)
    assert caches.retrieval.stats()["entries"] == 1
    assert [p.id for p in top_two[:1]] == [p.id for p in top_one]


def test_cached_result_matches_an_uncached_one():
    cold = _fresh_retriever().retrieve(QUESTION, k=3)
    warm_caches = Caches()
    warm = Retriever(CORPUS, caches=warm_caches).retrieve(QUESTION, k=3)
    again = Retriever(CORPUS, caches=warm_caches).retrieve(QUESTION, k=3)
    assert [p.id for p in cold] == [p.id for p in warm]
    assert [p.id for p in again] == [p.id for p in cold]


def test_cache_disabled_retrieves_without_storing():
    caches = Caches(enabled=False)
    retriever = Retriever(CORPUS, caches=caches)
    first = retriever.retrieve(QUESTION)
    second = retriever.retrieve(QUESTION)
    assert caches.retrieval.stats() == {"entries": 0, "hits": 0, "misses": 0}
    assert [p.id for p in second] == [p.id for p in first]


def test_different_corpus_never_reuses_retrieval():
    # The central promise: an edited document must not be answered
    # with passages ranked for the text it used to have.
    caches = Caches()
    before = Retriever(CORPUS, caches=caches)
    before_ids = [p.id for p in before.retrieve("Is KiteMetric audited?")]

    edited = [
        Passage(id=p.id, source=p.source, text=p.text + " Reviewed 2026-10.")
        for p in CORPUS
    ]
    after = Retriever(edited, caches=caches)
    assert after.corpus_hash != before.corpus_hash
    assert [p.id for p in after.retrieve("Is KiteMetric audited?")] == before_ids
    assert caches.retrieval.stats()["entries"] == 2


def test_a_retrieval_that_found_nothing_is_a_hit_not_a_miss():
    # An empty ranking is a real answer (hand the question off) and
    # must be cacheable as such — not confused with a miss.
    caches = Caches()
    retriever = Retriever(CORPUS, caches=caches)
    assert retriever.retrieve("Zebra xylophone quasar") == []
    assert retriever.retrieve("Zebra xylophone quasar") == []
    assert caches.retrieval.stats() == {"entries": 1, "hits": 1, "misses": 1}


def test_retrieval_cache_is_thread_safe():
    caches = Caches()
    retriever = Retriever(CORPUS, caches=caches)
    seen = []

    def worker():
        seen.append(
            tuple(p.id for p in retriever.retrieve(QUESTION, k=2))
        )

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(seen)) == 1


# ------------------------------------------------------------------
# Verdict cache
# ------------------------------------------------------------------

class CountingBackend:
    """A stand-in verifier with an identity, counting its calls."""

    def __init__(self, probability: float = 0.95, backend: str = "llm") -> None:
        self.probability = probability
        self.backend_name = backend
        self.calls = 0

    def claim_support(self, claim: str, passage: str) -> ClaimSupportResult:
        self.calls += 1
        return ClaimSupportResult(
            claim=claim,
            supported=self.probability >= 0.5,
            probability=self.probability,
            backend=self.backend_name,
        )


class IdentifiedBackend(CountingBackend):
    """A verifier that declares who it is, like ClaimSupportService."""

    identity = "llm|http://test|Qwen-model"
    primary_name = "llm"


def _checker(backend, caches: Caches) -> ClaimChecker:
    return ClaimChecker(support=backend, checker=None, caches=caches)


def _draft(claim_text: str, citations=("a-1",)) -> DraftResult:
    return DraftResult(
        question="q?",
        answer="",
        claims=[Claim(text=claim_text, citations=list(citations))],
        model="m",
    )


def test_repeated_claim_reuses_the_verdict():
    caches = Caches()
    backend = IdentifiedBackend()
    checker = _checker(backend, caches)
    checker.check_draft(_draft("Data is encrypted at rest"), CORPUS)
    checker.check_draft(_draft("Data is encrypted at rest"), CORPUS)
    assert backend.calls == 1
    assert caches.verdicts.stats() == {"entries": 1, "hits": 1, "misses": 1}


def test_cached_verdict_is_returned_verbatim():
    caches = Caches()
    backend = IdentifiedBackend(probability=0.42)
    checker = _checker(backend, caches)
    first = checker.check_draft(_draft("Ambiguous claim here"), CORPUS)
    second = checker.check_draft(_draft("Ambiguous claim here"), CORPUS)
    assert first.verdicts[0].precheck_probability == 0.42
    assert second.verdicts[0].precheck_probability == 0.42
    assert first.verdicts[0].precheck_backend == "llm"
    assert second.verdicts[0].route == first.verdicts[0].route


def test_a_near_duplicate_claim_must_miss():
    # The forbidden failure: a claim one character, one space, or one
    # case away from a judged one must be judged again itself.
    caches = Caches()
    backend = IdentifiedBackend()
    checker = _checker(backend, caches)
    judged = "Data is encrypted at rest"
    for variant in (
        "Data is encrypted at rest.",          # added full stop
        "Data is encrypted at rest ",         # trailing space
        " data is encrypted at rest",         # leading space
        "Data is encrypted at Rest",          # different case
        "Data is encrypted at rest?",         # different punctuation
        "Data is NOT encrypted at rest",      # one changed word
        "Data is encrypted at rest, always",  # extended
    ):
        backend.calls = 0
        checker.check_draft(_draft(variant), CORPUS)
        assert backend.calls == 1, f"{variant!r} was served from cache"


def test_a_different_passage_misses():
    caches = Caches()
    backend = IdentifiedBackend()
    checker = _checker(backend, caches)
    checker.check_draft(_draft("Audited", ["b-1"]), CORPUS)
    checker.check_draft(_draft("Audited", ["a-1"]), CORPUS)
    assert backend.calls == 2


def test_an_edited_passage_under_the_same_id_misses():
    # The id alone would be enough to collide here; the key carries
    # the text too, so an edited document is re-judged even though the
    # citation still says "a-1".
    caches = Caches()
    backend = IdentifiedBackend()
    checker = _checker(backend, caches)
    checker.check_draft(_draft("Encrypted at rest", ["a-1"]), CORPUS)
    edited = [EDITED_P, *CORPUS[1:]]
    assert edited[0].id == CORPUS[0].id  # same id, different text
    checker.check_draft(_draft("Encrypted at rest", ["a-1"]), edited)
    assert backend.calls == 2


def test_a_different_verifier_identity_misses():
    caches = Caches()
    first = IdentifiedBackend()
    second = IdentifiedBackend()

    class Other(IdentifiedBackend):
        identity = "llm|http://other-host|Qwen-model"

    _checker(first, caches).check_draft(_draft("Same claim"), CORPUS)
    _checker(Other(), caches).check_draft(_draft("Same claim"), CORPUS)
    assert first.calls == 1
    _checker(first, caches).check_draft(_draft("Same claim"), CORPUS)
    assert first.calls == 1


def test_a_pinned_version_change_misses():
    caches = Caches()
    backend = IdentifiedBackend()
    _checker(backend, caches).check_draft(_draft("Same claim"), CORPUS)

    class Bumped(IdentifiedBackend):
        identity = "jev|https://api.typesafe.ai|jev-1.14.0"

    bumped = Bumped()
    _checker(bumped, caches).check_draft(_draft("Same claim"), CORPUS)
    assert bumped.calls == 1


def test_an_unidentified_verifier_is_never_cached():
    # No identity means nothing to key on, so it is always asked.
    caches = Caches()
    backend = CountingBackend()
    checker = _checker(backend, caches)
    checker.check_draft(_draft("Data is encrypted"), CORPUS)
    checker.check_draft(_draft("Data is encrypted"), CORPUS)
    assert backend.calls == 2
    assert caches.verdicts.stats()["entries"] == 0


def test_a_rules_fallback_is_not_stored_as_the_model():
    # A degraded answer after a primary failure must not be frozen in
    # as that verifier's permanent view of the claim.
    caches = Caches()
    backend = IdentifiedBackend(probability=0.9, backend="rules")
    checker = _checker(backend, caches)
    checker.check_draft(_draft("Data is encrypted"), CORPUS)
    assert caches.verdicts.stats()["entries"] == 0

    backend.calls = 0
    checker.check_draft(_draft("Data is encrypted"), CORPUS)
    assert backend.calls == 1


def test_verdict_cache_disabled_asks_every_time():
    caches = Caches(enabled=False)
    backend = IdentifiedBackend()
    checker = _checker(backend, caches)
    checker.check_draft(_draft("Data is encrypted"), CORPUS)
    checker.check_draft(_draft("Data is encrypted"), CORPUS)
    assert backend.calls == 2
    assert caches.verdicts.stats()["entries"] == 0


def test_cached_verdicts_are_thread_safe():
    caches = Caches()
    backend = IdentifiedBackend()
    checker = _checker(backend, caches)
    claims = [Claim(text=f"Claim number {i} about encryption",
                    citations=["a-1"]) for i in range(6)]
    draft = DraftResult(question="q?", answer="", claims=claims, model="m")

    errors = []

    def worker():
        try:
            checker.check_draft(draft, CORPUS)
        except Exception as exc:  # pragma: no cover - only on a race
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert backend.calls == 6


def test_multi_citation_claims_key_on_every_citation():
    caches = Caches()
    backend = IdentifiedBackend()
    checker = _checker(backend, caches)
    checker.check_draft(_draft("Both facts", ["a-1", "b-1"]), CORPUS)
    checker.check_draft(_draft("Both facts", ["b-1", "a-1"]), CORPUS)
    # Same set, different order: the verifier saw a different passage
    # string, so it is asked again rather than reusing the verdict.
    assert backend.calls == 2


def test_verdict_cache_key_covers_the_passage_text():
    cache = VerdictCache()
    a = cache.key("c", [P1], "llm|host|model")
    b = cache.key("c", [EDITED], "llm|host|model")
    assert a != b


# ------------------------------------------------------------------
# Routing is unchanged by a cached probability
# ------------------------------------------------------------------

@pytest.mark.parametrize(
    "probability,route,verdict",
    [
        (0.95, "ship", "supported"),
        (0.80, "ship", "supported"),   # SHIP_AT, inclusive
        (0.79, "escalated", "uncertain"),
        (0.31, "escalated", "uncertain"),
        (0.30, "cut", "unsupported"),   # CUT_AT, inclusive
        (0.10, "cut", "unsupported"),
    ],
)
def test_the_bands_are_reapplied_to_a_cached_probability(
    probability, route, verdict
):
    # The cache stores the verifier's probability, never the route.
    # The bands are applied on every read, so a cached entry routes
    # exactly like a fresh one and a threshold change still bites.
    caches = Caches()
    checker = ClaimChecker(
        support=IdentifiedBackend(probability), checker=None, caches=caches
    )
    cold = checker.check_draft(_draft("Some claim"), CORPUS).verdicts[0]
    warm = checker.check_draft(_draft("Some claim"), CORPUS).verdicts[0]
    assert (cold.route, cold.verdict) == (route, verdict)
    assert (warm.route, warm.verdict) == (route, verdict)
    assert warm.precheck_probability == probability


def test_uncited_claims_are_never_cached():
    # No passage ids, nothing to key on; they go straight to the
    # checker, as before.
    caches = Caches()
    backend = IdentifiedBackend()
    checker = _checker(backend, caches)
    draft = DraftResult(
        question="q?", answer="",
        claims=[Claim(text="Uncited claim", citations=[])], model="m",
    )
    checker.check_draft(draft, CORPUS)
    checker.check_draft(draft, CORPUS)
    assert backend.calls == 0
    assert caches.verdicts.stats()["entries"] == 0


# ------------------------------------------------------------------
# Bypass for eval runs
# ------------------------------------------------------------------

def test_settings_flag_builds_a_disabled_cache_pair():
    assert caches_from_settings(Settings()).enabled is True
    assert caches_from_settings(Settings(cache_enabled=False)).enabled is False


def test_settings_flag_drives_the_claim_checker_factory():
    from app.checking import claim_checker_from_settings

    cold = claim_checker_from_settings(
        Settings(decision_backend="rules", cache_enabled=False)
    )
    assert cold._caches.enabled is False
    warm = claim_checker_from_settings(Settings(decision_backend="rules"))
    assert warm._caches.enabled is True


def test_process_wide_switch_reaches_retrievers():
    try:
        set_cache_enabled(False)
        retriever = Retriever(CORPUS)
        retriever.retrieve(QUESTION)
        assert cache_stats()["retrieval"]["entries"] == 0
        assert cache_stats()["enabled"] is False
        set_cache_enabled(True)
        retriever.retrieve(QUESTION)
        assert cache_stats()["retrieval"]["entries"] == 1
    finally:
        clear_caches()
        set_cache_enabled(True)


def test_cache_stats_report_both_caches():
    caches = Caches()
    caches.retrieval.put_ids("q", "corpus", ["a-1"])
    caches.verdicts.put("k", ClaimSupportResult("c", True, 1.0, "llm"))
    stats = caches.stats()
    assert stats["enabled"] is True
    assert stats["retrieval"]["entries"] == 1
    assert stats["verdicts"]["entries"] == 1


# ------------------------------------------------------------------
# Verifier identity
# ------------------------------------------------------------------

def test_claim_support_backend_name_covers_every_setting():
    assert claim_support_backend_name("llm") == "llm"
    assert claim_support_backend_name("jev") == "jev"
    assert claim_support_backend_name("rules") == "rules"
    # d3 is the default, and so is anything unrecognised.
    assert claim_support_backend_name("d3") == "d3"
    assert claim_support_backend_name("nonsense") == "d3"


def test_identity_names_backend_endpoint_and_pinned_version():
    llm = claim_support_identity(Settings(decision_backend="llm"))
    assert llm == "llm|http://localhost:8001/v1|vllm-sr/d3-lite"
    jev = claim_support_identity(Settings(decision_backend="jev"))
    assert jev == "jev|https://api.typesafe.ai|jev-1.13.0"
    rules = claim_support_identity(Settings(decision_backend="rules"))
    assert rules == "rules|1"


def test_identity_changes_with_the_model_and_the_host():
    base = Settings(decision_backend="llm")
    assert claim_support_identity(base) != claim_support_identity(
        Settings(decision_backend="llm", decision_model="other-model")
    )
    assert claim_support_identity(base) != claim_support_identity(
        Settings(decision_backend="llm", vllm_base_url="http://elsewhere")
    )
    assert claim_support_identity(
        Settings(decision_backend="jev")
    ) != claim_support_identity(
        Settings(decision_backend="jev", jev_model="jev-1.14.0")
    )


def test_rules_backend_verdicts_are_reproducible():
    # The rules backend is deterministic, so caching it is safe — the
    # cache simply declines to guess when no identity is declared.
    result = RulesClaimSupportBackend().claim_support(P1.text, P1.text)
    assert result == RulesClaimSupportBackend().claim_support(P1.text, P1.text)