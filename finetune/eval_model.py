"""Score a claim-support model on the held-out eval claims.

Works against any OpenAI-compatible chat endpoint: the base model
and the fine-tuned model served by MLX on the Mac, or the current
LLM decision layer on AMD Token Factory. Same system prompt and
user format as the app's decision layer (app/decision.py), so the
numbers describe the component ProofDesk actually calls.

    python finetune/eval_model.py --base-url http://localhost:8080/v1 \
        --model mlx-community/Qwen3.5-0.8B --label base

Metrics: supported-flag accuracy, probability MAE against the
constructed targets, and band behaviour (share of supported claims
scoring >= 0.80, share of unsupported claims scoring <= 0.30, and
the escalate band in between).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.decision import _CLAIM_SUPPORT_SYSTEM  # noqa: E402


def chat(base_url: str, model: str, claim: str, passage: str,
         api_key: str = "") -> dict:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _CLAIM_SUPPORT_SYSTEM},
            {"role": "user", "content": f"Claim: {claim}\n\nPassage: {passage}"},
        ],
        "temperature": 0.0,
        "max_tokens": 80,
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {api_key}"} if api_key else {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        out = json.loads(resp.read())
    text = out["choices"][0]["message"]["content"]
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--api-key", default="")
    ap.add_argument("--claims", default=str(ROOT / "finetune" / "data" / "eval_claims.jsonl"))
    args = ap.parse_args()

    rows = [json.loads(l) for l in Path(args.claims).read_text().splitlines() if l.strip()]
    correct = 0
    mae = 0.0
    ship = cut = esc = 0
    ship_ok = cut_ok = 0
    lat = []
    errors = 0
    for row in rows:
        t0 = time.time()
        try:
            got = chat(args.base_url, args.model, row["claim"], row["passage"], args.api_key)
            p = float(got["probability"])
            sup = bool(got["supported"])
        except Exception:
            errors += 1
            continue
        lat.append(time.time() - t0)
        if sup == row["supported"]:
            correct += 1
        mae += abs(p - row["probability"])
        if p >= 0.80:
            ship += 1
            ship_ok += row["supported"]
        elif p <= 0.30:
            cut += 1
            cut_ok += not row["supported"]
        else:
            esc += 1
    n = len(rows) - errors
    print(f"== {args.label} ({args.model}) on {len(rows)} held-out claims")
    print(f"   errors: {errors}")
    if n:
        print(f"   flag accuracy: {correct / n:.3f}")
        print(f"   probability MAE: {mae / n:.3f}")
        print(f"   bands: ship {ship} ({ship_ok} correct), cut {cut} "
              f"({cut_ok} correct), escalate {esc}")
        print(f"   latency p50: {sorted(lat)[len(lat) // 2]:.2f}s over {n} calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
