# Stage 1 — Retrieval (BM25)

Status: code complete, unit tests green, eval gate PENDING (results
appended below when the runs land).

## Problem

The drafting contract always said "the caller supplies the passages
(retrieval is a separate step)", but no retrieval step existed: the
questionnaire flow hand-bundled passages per question from the
sample pack (the question's source document, or the whole library).

## What changed

- `app/retrieval.py` (new): dependency-free Okapi BM25 (k1=1.5,
  b=0.75) over the corpus, significant-token rules shared with the
  lexical claim-support fallback (hyphenated part numbers stay one
  token). `Retriever` exposes `retrieve(question, k=8)`, `rank`,
  `top_match`, `score_against`, and a `corpus_hash` fingerprint.
  Zero-score passages are never returned.
- `app/sample.py`: `corpus_passages()`, `sample_questions()`
  (passage-free items), `sample_retriever()`.
- `app/answers.py`: `AnswerSheetService` takes an optional
  retriever; an item with no supplied passages is filled by
  retrieval and the entry records the chosen ids in the new
  `AnswerEntry.retrieved_passages` (also in the API output, the
  markdown sheet, and the /answers/sync round-trip).
- `app/main.py`: /questionnaire runs with the sample retriever;
  requests whose passages all come from the sample corpus are
  treated as sample-pack runs and re-retrieved per question, while
  foreign-corpus passages are used as supplied. /draft and /check
  retrieve from the sample corpus when no passages are supplied.
- `eval/run_eval.py`: the eval now exercises the retrieval flow.

Notable behaviour: the ISO 27001 trap question retrieves NOTHING
(no corpus passage shares a significant token with it — the
documents speak of SOC 2, never of ISO or certification), so it
hands off at the drafting step instead of drafting a claim that
then has to be blocked. The trap still cannot ship; the mechanism
moves earlier.

## Commands

Baseline (pre-stage code path, hand-bundled passages):

    .venv/bin/python -u hidden_files/measure_eval.py baseline <out.md>

Stage 1 (retrieval flow):

    .venv/bin/python -u hidden_files/measure_eval.py retrieval <out.md>

(measure_eval.py is the local runner: Token Factory surrogate via
authd, per-question timing, scoring by eval.run_eval.score.)

Unit tests:

    .venv/bin/python -m pytest tests/ -q

## Results

Baseline (2026-10-16 evening IST, hand-bundled passages, serial
per-question timing; raw file measure-baseline.md):

- **14/15 cases passed.** The miss is q13 (on-premises, expected
  hand-off, got answered) — the known flappy question: the drafter
  occasionally drafts an on-prem claim from the standard-offering
  passages and the pre-check passes it. Rounds 2–3 on 2026-10-15
  were also 14/15.
- **Total question time 677.0s.** Per-question spread is wide
  (q1 189.8s, q8 6.9s): the shared endpoint's load dominates
  individual timings, so totals are the headline and per-question
  numbers are indicative only.
- All 22 claim verdicts were decided by the decision pre-check;
  zero escalations to the checker in this run.

Stage 1 (retrieval flow): PENDING — appended when the run lands.
