# External eval stage 1: ContractNLI claim-support benchmark

## Why

The sample eval grades the whole pipeline on 15 hand-written
questions. This stage grades the *decision layer alone* (the
claim-support backends: rules, llm, jev) on 2,091 real human
judgements, and produces the probability distribution the Jev
ship threshold is calibrated from.

## Dataset

- **ContractNLI** — Koreeda & Manning, "ContractNLI: A Dataset
  for Document-level Natural Language Inference for Contracts",
  Findings of EMNLP 2021. https://aclanthology.org/2021.findings-emnlp.164
- Source: https://stanfordnlp.github.io/contract-nli/ (download:
  `resources/contract-nli.zip`, retrieved 2026-10-16).
- **Licence: CC BY 4.0**, per the official project page and the
  licence shipped in the download. (This corrects an earlier
  internal note that said Apache-2.0.) Attribution:
  `eval/external/data/CONTRACTNLI-ATTRIBUTION.md`.
- Test split: 123 contracts × 17 fixed hypotheses = **2,091
  items** — Entailment 968, NotMentioned 903, Contradiction 220.

## Design

ProofDesk claim support takes (claim, passage); ContractNLI is
document-level. Primary mode is **evidence-span mode**: the
hypothesis is the claim; the passage is its gold evidence spans
joined. NotMentioned items have no gold spans by definition; for
those the passage is the **top BM25 span from the same contract**
(the passage a real pipeline would most plausibly hand the
checker), or empty when no span shares vocabulary with the
hypothesis. The mode is recorded per item in the pairs file
(`passage_mode`: `gold-spans` / `bm25-top1` / `none`).

Label mapping, fail-closed like the product: Entailment →
supported; Contradiction, NotMentioned → not supported.
**False approvals** (gold ≠ Entailment, predicted supported) are
reported as their own number: they are the failure this product
exists to prevent.

Backends graded through the app's own `ClaimSupportService`, so
the benchmark measures exactly what ships:

- **rules** — full test split (local, instant).
- **jev** (jev-1.13.0) — full test split. Also the probability
  distribution by gold class, for threshold calibration.
- **llm** (DeepSeek-V4.1-Flash, the current decision model) —
  **stratified subset of 300**: proportional per gold class,
  deterministic shuffle with seed 42 (`stratified_subset` in the
  harness). The full split would burn ~2,091 calls on the shared
  Token Factory account the live demo needs; 300 is the quota
  guard's cap.

## Commands

```
# build the derived pairs file from the official test.json
python -m eval.external.contractnli build --data-dir <unzipped dir>

# grade (credentials via the environment, as the app reads them)
DECISION_BACKEND=rules python -m eval.external.contractnli grade --backend rules
DECISION_BACKEND=jev   python -m eval.external.contractnli grade --backend jev
DECISION_BACKEND=llm   python -m eval.external.contractnli grade --backend llm --subset stratified300
```

## Results

### rules (full test split, n=2,091)

- Accuracy **0.5921** — Entailment 0.5155 (n=968),
  Contradiction 0.5545 (n=220), NotMentioned 0.6833 (n=903).
- **False approvals: 384** (18.4% of all items). Lexical overlap
  approves contract language far too freely; the rules backend
  is an emergency fallback, and this number is the evidence.

### jev (full test split, n=2,091, at the adapter's 0.5 cut)

- Accuracy **0.8207** — Entailment 0.6498 (n=968),
  Contradiction 0.9091 (n=220), NotMentioned 0.9823 (n=903).
- **False approvals: 36** (1.7% of items; rules: 384).
- Fallbacks to rules: **0** — every verdict was really Jev.
- Median latency **767 ms** per call (this VM, via egress
  proxy, 4 workers).
- Probability distribution by gold class (the calibration
  evidence): Entailment p25 0.33 / median 0.66 / p75 0.86 /
  p90 0.96 — a third of truly supported claims score below the
  0.5 cut. NotMentioned median 0.02, p90 0.06; Contradiction
  median 0.01, p90 0.47. Jev is decisive when the answer is no
  and conservative when it is yes; the 0.5 cut spends that
  conservatism as lost Entailment recall.

### llm (stratified subset, n=300)

_Pending: runs after the Jev sample-eval gate, per the shared
quota guard._

## Notes

- Contract hypotheses are legal-English statements about NDAs,
  not security-questionnaire claims; absolute numbers will not
  transfer directly to the product domain. The *ordering* of
  backends and the *shape* of Jev's probability distribution are
  the portable findings.
