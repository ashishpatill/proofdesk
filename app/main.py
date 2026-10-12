"""ProofDesk app entry point.

Commit 1 scaffold: the FastAPI app object and configuration only.
The health endpoint and the vLLM client land in commit 2.
"""

from fastapi import FastAPI

from app.config import load_settings

settings = load_settings()

app = FastAPI(title="ProofDesk", version="0.1.0")
