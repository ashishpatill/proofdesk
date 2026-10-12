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
    evolus_api_base: str = ""
    evolus_api_key: str = ""


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
        evolus_api_base=os.environ.get("EVOLUS_API_BASE", ""),
        evolus_api_key=os.environ.get("EVOLUS_API_KEY", ""),
    )
