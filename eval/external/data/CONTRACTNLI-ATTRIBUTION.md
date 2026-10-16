# ContractNLI attribution

`contractnli_test_pairs.jsonl` in this directory is derived from
the **ContractNLI** dataset:

- Koreeda, Yuta and Manning, Christopher D. "ContractNLI: A
  Dataset for Document-level Natural Language Inference for
  Contracts." Findings of the Association for Computational
  Linguistics: EMNLP 2021, pp. 1907–1919.
  https://aclanthology.org/2021.findings-emnlp.164
- Source: https://stanfordnlp.github.io/contract-nli/
- Licence: **CC BY 4.0** (per the official project page and the
  licence file shipped with the download).

The derived file contains, per test-split item, the hypothesis
text, the gold label, and the passage our harness grades against
(the gold evidence spans joined, or the top BM25 span of the same
contract for NotMentioned items). It exists so the benchmark in
`eval/external/contractnli.py` runs without a 65 MB download.
