# ProofDesk

ProofDesk answers security and compliance questionnaires from a
company's own documents, and proves every answer before it ships.

A drafting model writes each answer with citations. A decision layer
scores every claim against its cited passage. Claims that cannot be
proven are cut or flagged for a human. What ships is an answer sheet
with an evidence trail: an AI auditor standing over the drafting
agent.

Built for the AMD Developer Hackathon: ACT III (Evolus Business
Agents track). All model inference runs on AMD Instinct MI300X
hardware on AMD Developer Cloud.

## Architecture

- Evolus: knowledge library holding the company documents, plus a
  workflow running the pipeline (at least two building blocks).
- This app (containerised): intake, triage, retrieval, drafting,
  claim splitting, claim checking, answer sheet rendering, and a
  human review queue for flagged items.
- Models, served on one MI300X droplet:
  - Qwen2.5-14B-Instruct (vLLM): the drafter.
  - Qwen2.5-32B-Instruct (vLLM): the checker of last resort for
    escalated claims.
  - vllm-sr d3-lite (0.85B): the decision layer for triage and
    claim-support pre-checks, served beside vLLM.

## Run locally

```bash
cp .env.example .env   # fill in endpoints and keys
docker compose up --build
curl http://localhost:8000/health
```

## Status

Build in progress during the hackathon window (Oct 12-18, 2026).
Progress and eval numbers land in this README as they are measured.
