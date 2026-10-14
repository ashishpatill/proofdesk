# ProofDesk eval results

- Drafter model: DeepSeek-V4.1-Flash
- Checker model: Qwen3.8-27B
- Decision backend: llm (DeepSeek-V4.1-Flash)
- Model endpoint: https://developer.amd.com.cn/radeon/api/v1

| Case | Expected | Result | Detail |
|---|---|---|---|
| q1 | answerable | PASS | status=answered (want answered/partial) |
| q2 | answerable | PASS | status=answered (want answered/partial) |
| q3 | answerable | PASS | status=answered (want answered/partial) |
| q4 | answerable | FAIL | status=handoff (want answered/partial) |
| q5 | answerable | FAIL | status=handoff (want answered/partial) |
| q6 | answerable | FAIL | status=handoff (want answered/partial) |
| q7 | answerable | FAIL | status=handoff (want answered/partial) |
| q8 | answerable | FAIL | status=handoff (want answered/partial) |
| q9 | answerable | FAIL | status=handoff (want answered/partial) |
| q10 | answerable | PASS | status=answered (want answered/partial) |
| q11 | answerable | PASS | status=answered (want answered/partial) |
| q12 | trap | PASS | trap claim shipped=False (want False) |
| q13 | unanswerable | FAIL | status=answered (want handoff) |
| q14 | unanswerable | PASS | status=handoff (want handoff) |
| q15 | unanswerable | FAIL | status=answered (want handoff) |

**7/15 cases passed.**
