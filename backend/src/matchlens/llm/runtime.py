from collections.abc import Callable
from typing import Any, override

from matchlens.config import LLMMode, Settings
from matchlens.llm.client import LLMClient, LLMDisabledError, create_llm_client
from matchlens.llm.fixtures import live_responses
from matchlens.models.traces import AgentName, AgentTrace


class RuntimeLLMClient(LLMClient):
    def __init__(self, settings: Settings, record_trace: Callable[[AgentTrace], None]) -> None:
        self.mode = settings.llm_mode
        self.calls = 0
        self.models_used: dict[str, set[str]] = {}
        self._settings = settings
        self._record_trace = record_trace
        self._clients: dict[LLMMode, LLMClient] = {}

    def set_mode(self, mode: LLMMode) -> None:
        Settings.model_validate({**self._settings.model_dump(), "llm_mode": mode})
        self.mode = mode

    @override
    async def complete_json(
        self,
        agent: AgentName,
        system: str,
        user: str,
        schema: dict[str, Any],
        model: str,
        *,
        match_id: str = "system",
        moment_id: str | None = None,
    ) -> dict[str, Any]:
        if self.calls >= self._settings.max_llm_calls_per_match and self.mode is not LLMMode.OFF:
            raise LLMDisabledError("per-match LLM call budget exhausted")
        if self.mode not in self._clients:
            configured = self._settings.model_copy(update={"llm_mode": self.mode})
            self._clients[self.mode] = create_llm_client(
                configured, live_responses(), self._record_trace
            )
        if self.mode is not LLMMode.OFF:
            self.calls += 1
            if moment_id is not None:
                self.models_used.setdefault(moment_id, set()).add(model)
        return await self._clients[self.mode].complete_json(
            agent, system, user, schema, model, match_id=match_id, moment_id=moment_id
        )
