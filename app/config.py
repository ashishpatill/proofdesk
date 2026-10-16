"""Environment configuration. Keys live in env vars only, never in code."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    vllm_base_url: str = "http://localhost:8001/v1"
    vllm_api_key: str = ""
    drafter_model: str = "Qwen/Qwen2.5-14B-Instruct"
    checker_model: str = "Qwen/Qwen2.5-32B-Instruct"
    decision_base_url: str = "http://localhost:8002"
    decision_model: str = "vllm-sr/d3-lite"
    decision_backend: str = "d3"  # "d3" | "llm" | "jev" | "rules"
    typesafe_base_url: str = "https://api.typesafe.ai"
    typesafe_api_key: str = ""
    jev_model: str = "jev-1.13.0"  # pinned; jev-latest moves
    evolus_api_base: str = ""
    evolus_api_key: str = ""
    evolus_application_id: str = ""
    evolus_workflow_id: str = ""


def load_settings() -> Settings:
    return Settings(
        vllm_base_url=os.environ.get("VLLM_BASE_URL", Settings.vllm_base_url),
        vllm_api_key=os.environ.get("VLLM_API_KEY", ""),
        drafter_model=os.environ.get("DRAFTER_MODEL", Settings.drafter_model),
        checker_model=os.environ.get("CHECKER_MODEL", Settings.checker_model),
        decision_base_url=os.environ.get(
            "DECISION_BASE_URL", Settings.decision_base_url
        ),
        decision_model=os.environ.get("DECISION_MODEL", Settings.decision_model),
        decision_backend=os.environ.get(
            "DECISION_BACKEND", Settings.decision_backend
        ),
        typesafe_base_url=os.environ.get(
            "TYPESAFE_BASE_URL", Settings.typesafe_base_url
        ),
        typesafe_api_key=os.environ.get("TYPESAFE_API_KEY", ""),
        jev_model=os.environ.get("JEV_MODEL", Settings.jev_model),
        evolus_api_base=os.environ.get("EVOLUS_API_BASE", ""),
        evolus_api_key=os.environ.get("EVOLUS_API_KEY", ""),
        evolus_application_id=os.environ.get("EVOLUS_APPLICATION_ID", ""),
        evolus_workflow_id=os.environ.get("EVOLUS_WORKFLOW_ID", ""),
    )
