"""Minimal OpenAI-compatible client for the vLLM server on the droplet.

vLLM serves an OpenAI-shaped API, so ProofDesk only needs model
listing and chat completions. Keys come from settings (env vars),
never from code.
"""

from __future__ import annotations

import time

import httpx

from app.config import Settings


class VLLMError(RuntimeError):
    pass


class VLLMClient:
    def __init__(self, settings: Settings, timeout: float = 30.0) -> None:
        self._base = settings.vllm_base_url.rstrip("/")
        self._timeout = timeout
        headers = {}
        if settings.vllm_api_key:
            headers["Authorization"] = f"Bearer {settings.vllm_api_key}"
        self._headers = headers

    def list_models(self) -> list[str]:
        try:
            # trust_env=False: droplet traffic is direct infrastructure
            # traffic and must never be routed through an env proxy.
            resp = httpx.get(
                f"{self._base}/models",
                headers=self._headers,
                timeout=self._timeout,
                trust_env=False,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise VLLMError(f"vLLM model list failed: {exc}") from exc
        return [item["id"] for item in resp.json().get("data", [])]

    def probe(self) -> dict:
        """Health probe: reachable plus the models the server reports."""
        try:
            models = self.list_models()
        except VLLMError as exc:
            return {"reachable": False, "models": [], "error": str(exc)}
        return {"reachable": True, "models": models, "error": None}

    def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # Rate-limited endpoints (AMD Token Factory: 30 RPM per key)
        # answer bursts with 429. Honour Retry-After when sent, else
        # back off briefly; three retries, then the error stands.
        delays = [2.0, 5.0, 12.0]
        for attempt in range(len(delays) + 1):
            try:
                resp = httpx.post(
                    f"{self._base}/chat/completions",
                    headers=self._headers,
                    json=payload,
                    timeout=self._timeout,
                    trust_env=False,
                )
                if resp.status_code in (429, 503) and attempt < len(delays):
                    retry_after = resp.headers.get("Retry-After", "")
                    delay = (
                        float(retry_after)
                        if retry_after.replace(".", "", 1).isdigit()
                        else delays[attempt]
                    )
                    time.sleep(min(delay, 20.0))
                    continue
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise VLLMError(f"vLLM chat completion failed: {exc}") from exc
            choices = resp.json().get("choices", [])
            if not choices:
                raise VLLMError("vLLM returned no choices")
            return choices[0]["message"]["content"]
        raise VLLMError("vLLM chat completion failed: rate limited, retries exhausted")
