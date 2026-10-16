"""Sample pack access: the fictional KiteMetric documents and the
labelled questionnaire, shared by the demo UI and the eval harness.

Passages are paragraphs of the sample documents. A question with a
source_doc draws its passages from that document; the rest draw from
the whole library, the way a real desk would search everything it
holds. That hand-bundling is what /sample serves; the questionnaire
and eval flows proper use retrieval instead (sample_questions +
sample_retriever): every question is searched against the full
corpus, the way a real desk's retrieval step would.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.answers import QuestionItem
from app.drafting import Passage
from app.retrieval import Retriever

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample"


def load_passages(sample_dir: Path = SAMPLE_DIR) -> dict[str, list[Passage]]:
    per_doc: dict[str, list[Passage]] = {}
    for path in sorted(sample_dir.glob("*.md")):
        passages = []
        for i, chunk in enumerate(path.read_text().split("\n\n")):
            text = " ".join(chunk.split())
            if len(text) >= 40 and not text.startswith("#"):
                passages.append(
                    Passage(id=f"{path.stem}-{i}", source=path.name, text=text)
                )
        per_doc[path.name] = passages
    return per_doc


def load_pack(sample_dir: Path = SAMPLE_DIR) -> dict:
    return json.loads((sample_dir / "questionnaire.json").read_text())


def sample_items(sample_dir: Path = SAMPLE_DIR) -> list[QuestionItem]:
    pack = load_pack(sample_dir)
    per_doc = load_passages(sample_dir)
    items = []
    for q in pack["questions"]:
        if q.get("source_doc") in per_doc:
            passages = per_doc[q["source_doc"]]
        else:
            passages = [p for docs in per_doc.values() for p in docs]
        items.append(QuestionItem(question=q["question"], passages=passages))
    return items


def corpus_passages(sample_dir: Path = SAMPLE_DIR) -> list[Passage]:
    """The whole sample library as one flat corpus, in document
    order — the document set retrieval searches."""
    per_doc = load_passages(sample_dir)
    return [p for docs in per_doc.values() for p in docs]


def sample_questions(sample_dir: Path = SAMPLE_DIR) -> list[QuestionItem]:
    """The questionnaire with no passages attached: the retrieval
    flow. The answer-sheet service fills each item's passages from
    the retriever instead of a hand bundle."""
    pack = load_pack(sample_dir)
    return [
        QuestionItem(question=q["question"], passages=[])
        for q in pack["questions"]
    ]


def sample_retriever(sample_dir: Path = SAMPLE_DIR) -> Retriever:
    return Retriever(corpus_passages(sample_dir))
