import asyncio
import importlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from math import ceil
from typing import Any, Protocol, cast
from uuid import uuid4

from matchlens.config import LLMMode, Settings
from matchlens.models.traces import AgentName, AgentTrace, TraceStatus

TraceRecorder = Callable[[AgentTrace], None]


class FoundryResponse(Protocol):
    text: str
    usage_details: dict[str, int] | None


class FoundryChatClient(Protocol):
    async def get_response(
        self, messages: list[Any], *, options: dict[str, Any]
    ) -> FoundryResponse: ...


def _ignore_trace(trace: AgentTrace) -> None:
    del trace


class LLMDisabledError(RuntimeError):
    pass


class LLMClient(Protocol):
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
    ) -> dict[str, Any]: ...


class OffLLMClient:
    def __init__(self, record_trace: TraceRecorder | None = None) -> None:
        self._record_trace = record_trace if record_trace is not None else _ignore_trace

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
        self._record_trace(
            _trace(
                agent,
                match_id,
                moment_id,
                "complete_json",
                status="fallback",
                latency_ms=0,
                tokens_in=ceil((len(system) + len(user)) / 4),
                tokens_out=0,
                detail="LLM mode is off",
            )
        )
        raise LLMDisabledError(f"LLM mode is off for {agent}")


class MockLLMClient:
    def __init__(
        self,
        responses: Mapping[tuple[AgentName, str], dict[str, Any]],
        record_trace: TraceRecorder | None = None,
    ) -> None:
        self._responses = responses
        self._record_trace = record_trace if record_trace is not None else _ignore_trace

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
        started = asyncio.get_running_loop().time()
        moment_type = _moment_type(user)
        status: TraceStatus = "ok"
        detail = f"model={model}; fixture={moment_type}"
        tokens_out = 0
        try:
            response = self._responses.get((agent, moment_type))
            if response is None:
                response = self._responses.get((agent, "default"))
            if response is None:
                raise LookupError(f"no mock response for {agent}/{moment_type}")
            result = cast("dict[str, Any]", json.loads(json.dumps(response)))
            tokens_out = ceil(len(json.dumps(result)) / 4)
            return result
        except Exception as error:
            status = "error"
            detail = f"{type(error).__name__}: {error}"[:200]
            raise
        finally:
            self._record_trace(
                _trace(
                    agent,
                    match_id,
                    moment_id,
                    "complete_json",
                    status=status,
                    latency_ms=(asyncio.get_running_loop().time() - started) * 1000,
                    tokens_in=ceil((len(system) + len(user)) / 4),
                    tokens_out=tokens_out,
                    detail=detail,
                )
            )
        return result


class FoundryLLMClient:
    def __init__(self, settings: Settings, record_trace: TraceRecorder | None = None) -> None:
        try:
            foundry_module = cast("Any", importlib.import_module("agent_framework.foundry"))
            identity_module = cast("Any", importlib.import_module("azure.identity.aio"))
            framework_module = cast("Any", importlib.import_module("agent_framework"))
        except ImportError as error:
            raise RuntimeError("install the backend 'foundry' extra to use Foundry mode") from error

        foundry_client = foundry_module.FoundryChatClient
        azure_cli_credential = identity_module.AzureCliCredential
        message_type = framework_module.Message
        self._client: FoundryChatClient = cast(
            "FoundryChatClient",
            foundry_client(
                project_endpoint=settings.foundry_project_endpoint,
                model=settings.fast_model,
                credential=azure_cli_credential(),
            ),
        )
        self._message_type = message_type
        self._record_trace = record_trace if record_trace is not None else _ignore_trace

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
        started = asyncio.get_running_loop().time()
        status: TraceStatus = "ok"
        detail = f"model={model}"
        tokens_in = ceil((len(system) + len(user)) / 4)
        tokens_out = 0
        try:
            messages = [self._message_type("system", [system]), self._message_type("user", [user])]
            options = {
                "model": model,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": agent, "schema": schema, "strict": True},
                },
            }
            response, retried = await self._complete_with_retry(messages, options)
            if retried:
                status = "retry"
                detail = f"{detail}; transport retry"
            payload: object = json.loads(response.text)
            if not isinstance(payload, dict):
                raise ValueError("structured response must be a JSON object")
            result = cast("dict[str, Any]", payload)
            if response.usage_details is not None:
                tokens_in = response.usage_details.get("input_token_count", tokens_in)
                tokens_out = response.usage_details.get("output_token_count", 0)
            return result
        except Exception as error:
            status = "error"
            detail = f"{type(error).__name__}: {error}"[:200]
            raise
        finally:
            self._record_trace(
                _trace(
                    agent,
                    match_id,
                    moment_id,
                    "complete_json",
                    status=status,
                    latency_ms=(asyncio.get_running_loop().time() - started) * 1000,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    detail=detail,
                )
            )

    async def _complete_with_retry(
        self, messages: list[Any], options: dict[str, Any]
    ) -> tuple[FoundryResponse, bool]:
        started = asyncio.get_running_loop().time()
        for attempt in range(2):
            try:
                response = await asyncio.wait_for(
                    self._client.get_response(messages, options=options),
                    timeout=max(0.01, 8 - (asyncio.get_running_loop().time() - started)),
                )
                return response, attempt > 0
            except Exception as error:
                if attempt or not _is_transport_error(error):
                    raise
        raise RuntimeError("Foundry request did not return a response")


def create_llm_client(
    settings: Settings,
    mock_responses: Mapping[tuple[AgentName, str], dict[str, Any]] | None = None,
    record_trace: TraceRecorder | None = None,
) -> LLMClient:
    if settings.llm_mode is LLMMode.OFF:
        return OffLLMClient(record_trace)
    if settings.llm_mode is LLMMode.MOCK:
        return MockLLMClient(mock_responses or {}, record_trace)
    return FoundryLLMClient(settings, record_trace)


def _moment_type(user: str) -> str:
    try:
        payload: object = json.loads(user)
    except json.JSONDecodeError:
        return "default"
    if not isinstance(payload, dict):
        return "default"
    values = cast("dict[str, Any]", payload)
    value = values.get("moment_type", values.get("type", "default"))
    return value if isinstance(value, str) else "default"


def _is_transport_error(error: Exception) -> bool:
    return isinstance(error, (TimeoutError, ConnectionError, OSError)) or type(error).__name__ in {
        "ServiceRequestError",
        "ServiceResponseError",
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
    }


def _trace(
    agent: AgentName,
    match_id: str,
    moment_id: str | None,
    action: str,
    *,
    status: TraceStatus,
    latency_ms: float,
    tokens_in: int,
    tokens_out: int,
    detail: str,
) -> AgentTrace:
    return AgentTrace(
        trace_id=uuid4().hex,
        match_id=match_id,
        moment_id=moment_id,
        agent=agent,
        action=action,
        status=status,
        latency_ms=round(latency_ms),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        detail=detail,
        ts=datetime.now(UTC),
    )
