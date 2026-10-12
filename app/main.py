"""ProofDesk app entry point.

Commit 2: health endpoint backed by a vLLM probe, plus the vLLM
client the drafting and checking pipelines will use.
"""

from fastapi import FastAPI

from app.config import load_settings
from app.vllm_client import VLLMClient

settings = load_settings()

app = FastAPI(title="ProofDesk", version="0.1.0")


@app.get("/health")
def health() -> dict:
    probe = VLLMClient(settings, timeout=3.0).probe()
    return {
        "status": "ok",
        "drafter_model": settings.drafter_model,
        "checker_model": settings.checker_model,
        "decision_model": settings.decision_model,
        "vllm": probe,
    }
