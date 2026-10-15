# Fine-tune runbook (Mac Mini M1, 16 GB)

Goal: a LoRA fine-tune of Qwen/Qwen3.5-0.8B (the vllm-sr/d3-lite
base) for ProofDesk's claim-support decision, evaluated against the
base model and the current LLM decision layer on held-out claims
from a company training never saw (Northwind, finetune/data/
eval_claims.jsonl). Ship only if the tuned model wins.

## 0. Setup

```bash
cd ~/proofdesk   # this repo, pulled to latest master
python3 -m venv .venv-ft && source .venv-ft/bin/activate
pip install -U mlx-lm huggingface_hub
```

If `mlx_lm` cannot load Qwen/Qwen3.5-0.8B (architecture too new for
the installed mlx-lm), upgrade mlx-lm once; if it still fails, stop
and report — the fallback is PyTorch MPS (transformers Trainer,
LoRA via peft), same data files.

## 1. Data (already generated and committed)

finetune/data/train.jsonl + valid.jsonl are MLX chat-format files
built by finetune/build_data.py (labels correct by construction).
Regenerate only if the docs changed:
`python finetune/build_data.py`

## 2. Baseline first

Serve the BASE model and score it before training anything:

```bash
mlx_lm.server --model Qwen/Qwen3.5-0.8B --port 8080 &
python finetune/eval_model.py --base-url http://localhost:8080/v1 \
    --model Qwen/Qwen3.5-0.8B --label base
```

## 3. Train

```bash
mlx_lm.lora --config finetune/lora_config.yaml
```

Expected: well under an hour at ~1-2k short examples on the M1.
Watch the validation loss at each eval step; it should fall below
the initial value and keep improving or plateau, not diverge.

## 4. Score the tuned model

```bash
mlx_lm.fuse --model Qwen/Qwen3.5-0.8B \
    --adapter-path finetune/adapters --save-path finetune/fused
mlx_lm.server --model finetune/fused --port 8081 &
python finetune/eval_model.py --base-url http://localhost:8081/v1 \
    --model finetune/fused --label tuned
```

## 5. Report

Report both scoreboards (base vs tuned): flag accuracy, MAE, band
counts, latency. Also keep the training log tail. The decision to
ship is gated on the tuned model beating the base on flag accuracy
without worse band behaviour.
