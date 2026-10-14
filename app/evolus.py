"""Evolus workspace client: ProofDesk drives Evolus through its APIs.

Built for the AMD Developer Hackathon Act III Evolus track. Evolus
exposes (per the event's technical resources):

- REST API at https://api.evolus.ai/api/v1 with X-ApiKey and
  X-Application-Id headers: workflows (POST /workflows/{id}/execute),
  AI Tools (POST /ai-tools/{tool}/run), knowledge libraries, agents.
- An OpenAI-compatible agent-chat endpoint at https://api.evolus.ai/v1
  where the model name is "<applicationId>:<agentId>" and the API key
  is the Bearer token.

ProofDesk uses two Evolus building blocks: a workflow that receives
the finished answer sheet for the business process in Evolus, and AI
Tools for document utilities. Keys come from settings (env vars),
never from code. Every failure raises EvolusError; nothing here
pretends a call succeeded.
"""

from __future__ import annotations

import httpx

from app.config import Settings


class EvolusError(RuntimeError):
    pass


class EvolusClient:
    def __init__(self, settings: Settings, timeout: float = 30.0) -> None:
        self._base = (settings.evolus_api_base or "https://api.evolus.ai").rstrip("/")
        self._api_key = settings.evolus_api_key
        self._application_id = settings.evolus_application_id
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self._application_id)

    def _headers(self) -> dict:
        return {
            "X-ApiKey": self._api_key,
            "X-Application-Id": self._application_id,
        }

    def _post(self, path: str, payload: dict) -> dict:
        try:
            resp = httpx.post(
                f"{self._base}/api/v1{path}",
                headers=self._headers(),
                json=payload,
                timeout=self._timeout,
                trust_env=False,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise EvolusError(f"Evolus POST {path} failed: {exc}") from exc
        data = resp.json()
        if not isinstance(data, dict):
            raise EvolusError(f"Evolus POST {path} returned a non-object body")
        return data

    def execute_workflow(self, workflow_id: str, inputs: dict) -> dict:
        """Start a workflow execution with text inputs; returns the
        API's execution record (id and status as Evolus reports them)."""
        if not workflow_id:
            raise EvolusError("no workflow id configured")
        return self._post(f"/workflows/{workflow_id}/execute", inputs)

    def run_ai_tool(self, tool: str, payload: dict) -> dict:
        """Run one of the ready-made AI Tools (document to structured
        data, text comparison, summarisation, ...)."""
        if not tool:
            raise EvolusError("no AI tool named")
        return self._post(f"/ai-tools/{tool}/run", payload)

    def agent_chat(self, agent_id: str, message: str) -> str:
        """Chat with a workspace agent through the OpenAI-compatible
        endpoint; the model name is "<applicationId>:<agentId>"."""
        if not agent_id:
            raise EvolusError("no agent id given")
        payload = {
            "model": f"{self._application_id}:{agent_id}",
            "messages": [{"role": "user", "content": message}],
        }
        try:
            resp = httpx.post(
                f"{self._base}/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
                timeout=self._timeout,
                trust_env=False,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise EvolusError(f"Evolus agent chat failed: {exc}") from exc
        choices = resp.json().get("choices", [])
        if not choices:
            raise EvolusError("Evolus agent chat returned no choices")
        return choices[0]["message"]["content"]


def evolus_client_from_settings(settings: Settings) -> EvolusClient | None:
    """None when the workspace is not configured, so the app can say
    so plainly instead of failing mid-request."""
    client = EvolusClient(settings)
    return client if client.configured else None
