# ProofDesk

https://github.com/user-attachments/assets/bf9648c0-3b57-4054-becd-bead09efd685

ProofDesk answers security and compliance questionnaires from a
company's own documents, and proves every answer before it ships.

A drafting model writes each answer with citations. A decision layer
scores every claim against its cited passage. Claims that cannot be
proven are cut or flagged for a human. What ships is an answer sheet
with an evidence trail: an AI auditor standing over the drafting
agent.

Built for the AMD Developer Hackathon: ACT III (Evolus Business
Agents track). All model inference runs on open models served by
AMD Token Factory, AMD's hosted serving for the event: no billing,
a daily usage cap, OpenAI-compatible API.

## Architecture

- Evolus: a workflow ("ProofDesk Answer Sheet Intake") that receives
  the finished answer sheet through the Evolus API and continues the
  business process, plus a knowledge library holding the company
  documents.
- This app (containerised FastAPI, also deployed on Vercel): intake,
  triage, drafting, claim splitting, claim checking, answer sheet
  rendering, and a human review queue for flagged items. The demo UI
  runs questions through a paced parallel runner (three in flight,
  pause/stop, duplicate-run guard) that respects the endpoint's
  20-requests-per-minute limit, and shows the remaining daily budget.
- Models, served by AMD Token Factory:
  - DeepSeek-V4.1-Flash: the drafter, and the decision layer for
    triage and claim-support pre-checks (0.80/0.30 routing bands).
  - Qwen3.8-27B: the checker of last resort for escalated claims —
    a different model family from the drafter, on purpose.

## Run locally

```bash
cp .env.example .env   # fill in endpoints and keys
docker compose up --build
curl http://localhost:8000/health
```

## Eval

On the labelled 15-question sample pack (11 answerable, 3 the
documents cannot answer, 1 trap — an ISO 27001 question where the
documents support SOC 2 only): **14/15**, the trap blocked, and zero
unsupported claims shipped. Full table: eval/results.md.

## Status

Live demo: https://proofdesk-nine.vercel.app — health endpoint
reports the models reachable and the remaining daily budget.

A fine-tune of the decision layer (LoRA on Qwen3.5-0.8B, the d3-lite
base, trained on the Mac) is in progress under finetune/ with a
ship-only-if-it-beats-the-baseline gate; the shipped build above
does not depend on it.
