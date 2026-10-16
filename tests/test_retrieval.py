"""Retrieval tests: BM25 ranking over the sample corpus, and the
answer-sheet service's retrieval path (questions with no supplied
passages get the retriever's choice, recorded on the entry)."""

from app.answers import AnswerSheetService, QuestionItem
from app.checking import ClaimChecker
from app.config import Settings
from app.decision import ClaimSupportService
from app.drafting import Claim, DraftResult, Passage
from app.retrieval import Retriever, tokenise
from app.sample import corpus_passages, sample_retriever


def test_tokenise_keeps_part_numbers_drops_stopwords():
    toks = tokenise("Is the data encrypted with AES-256 or TLS 1.2?")
    assert "aes-256" in toks
    assert "encrypted" in toks
    assert "the" not in toks and "is" not in toks


def test_encryption_question_ranks_security_policy_first():
    retriever = sample_retriever()
    top = retriever.retrieve(
        "How is customer data encrypted at rest and in transit?"
    )
    assert top and top[0].source == "security-policy.md"


def test_breach_question_ranks_incident_response_first():
    retriever = sample_retriever()
    top = retriever.retrieve(
        "Within what timeframe do you notify customers of a "
        "confirmed data breach?"
    )
    assert top and top[0].source == "incident-response-plan.md"


def test_trap_question_retrieves_nothing():
    # No passage shares a significant token with the ISO 27001
    # question (the documents speak of SOC 2, never of ISO or
    # certification), so retrieval returns nothing and the pipeline
    # hands the question off instead of drafting from noise.
    retriever = sample_retriever()
    assert retriever.retrieve("Are you ISO 27001 certified?") == []


def test_soc2_question_finds_the_soc2_passage():
    retriever = sample_retriever()
    top = retriever.retrieve("Do you have a SOC 2 report available?")
    assert top and "SOC 2" in top[0].text


def test_no_shared_vocabulary_retrieves_nothing():
    retriever = sample_retriever()
    assert retriever.retrieve("Zebra xylophone quasar jambalaya") == []


def test_ranking_is_deterministic():
    retriever = sample_retriever()
    q = "How long is customer data retained after contract termination?"
    assert [p.id for p in retriever.retrieve(q)] == [
        p.id for p in retriever.retrieve(q)
    ]


class _Drafting:
    """Drafts one claim citing the first passage it was given."""

    def draft(self, question, passages):
        if not passages:
            return DraftResult(question=question, answer="", claims=[],
                               model="fake")
        first = passages[0]
        return DraftResult(
            question=question,
            answer=first.text,
            claims=[Claim(text=first.text, citations=[first.id])],
            model="fake",
        )


def _service(retriever):
    checker = ClaimChecker(
        support=ClaimSupportService(Settings()), checker=None
    )
    return AnswerSheetService(
        drafting=_Drafting(), checker=checker, retriever=retriever
    )


def test_service_retrieves_and_records_passage_ids():
    corpus = corpus_passages()
    service = _service(Retriever(corpus))
    sheet = service.build(
        [QuestionItem(
            question="How is customer data encrypted at rest and in transit?",
            passages=[],
        )]
    )
    entry = sheet.entries[0]
    assert entry.retrieved_passages
    assert entry.retrieved_passages[0].startswith("security-policy")
    assert entry.status == "answered"


def test_supplied_passages_win_over_retrieval():
    corpus = corpus_passages()
    service = _service(Retriever(corpus))
    supplied = [corpus[0]]
    sheet = service.build(
        [QuestionItem(question="Anything?", passages=supplied)]
    )
    assert sheet.entries[0].retrieved_passages == []
