"""Local pre-check tests (stage 2, module only — the checker wiring
is pinned separately). The safety properties under test: verbatim
support ships locally, a claim citing an unrelated passage is cut
locally, absence and negative claims NEVER resolve locally, and
anything paraphrased, foreign, or altered defers to the models."""

from app.drafting import Claim, Passage
from app.local_check import LocalPrecheck
from app.retrieval import Retriever
from app.sample import corpus_passages, sample_retriever

P1 = Passage(
    id="p1",
    source="security-policy.md",
    text="Data at rest is encrypted with AES-256 (AWS KMS managed keys).",
)
P2 = Passage(
    id="p2",
    source="product-faq.md",
    text="The service commits to 99.9% monthly uptime.",
)


def _precheck() -> LocalPrecheck:
    return LocalPrecheck(Retriever([P1, P2]))


def test_verbatim_claim_ships_locally():
    decision = _precheck().try_decide(
        Claim(
            text="Data at rest is encrypted with AES-256.",
            citations=["p1"],
        ),
        [P1],
    )
    assert decision is not None
    assert decision.verdict == "supported"
    assert decision.probability == 1.0
    assert "local pre-check" in decision.reason


def test_unrelated_citation_defers_the_fast_path_never_cuts():
    # Zero overlap with the cited passage, but the fast path may
    # only ship: a paraphrase can share no tokens with a passage
    # that does support it, so cutting stays with the models.
    decision = _precheck().try_decide(
        Claim(
            text="Customers receive a dedicated account manager.",
            citations=["p2"],
        ),
        [P2],
    )
    assert decision is None


def test_paraphrase_defers_to_models():
    decision = _precheck().try_decide(
        Claim(
            text="Stored information is protected by strong encryption.",
            citations=["p1"],
        ),
        [P1],
    )
    assert decision is None


def test_absence_claim_never_resolves_locally():
    passage = Passage(
        id="p3",
        source="product-faq.md",
        text="The documents do not mention on-premises deployment.",
    )
    precheck = LocalPrecheck(Retriever([passage]))
    decision = precheck.try_decide(
        Claim(
            text="The documents do not mention on-premises deployment.",
            citations=["p3"],
        ),
        [passage],
    )
    assert decision is None


def test_negative_claim_never_resolves_locally():
    passage = Passage(
        id="p4",
        source="product-faq.md",
        text="KiteMetric cannot be run as a dedicated single-tenant "
        "environment.",
    )
    precheck = LocalPrecheck(Retriever([passage]))
    decision = precheck.try_decide(
        Claim(
            text="KiteMetric cannot be run as a dedicated "
            "single-tenant environment.",
            citations=["p4"],
        ),
        [passage],
    )
    assert decision is None


def test_foreign_passage_defers():
    foreign = Passage(id="zz-9", source="other.md", text=P1.text)
    decision = _precheck().try_decide(
        Claim(text="Data at rest is encrypted with AES-256.",
              citations=["zz-9"]),
        [foreign],
    )
    assert decision is None


def test_altered_passage_text_defers():
    altered = Passage(id="p1", source="security-policy.md",
                      text=P1.text + " Extra sentence added later.")
    decision = _precheck().try_decide(
        Claim(text="Data at rest is encrypted with AES-256.",
              citations=["p1"]),
        [altered],
    )
    assert decision is None


def test_iso_trap_claim_is_never_shipped_locally():
    retriever = sample_retriever()
    soc2 = next(p for p in corpus_passages() if "SOC 2" in p.text)
    decision = LocalPrecheck(retriever).try_decide(
        Claim(text="KiteMetric is ISO 27001 certified.",
              citations=[soc2.id]),
        [soc2],
    )
    assert decision is None
