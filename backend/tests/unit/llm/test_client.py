import asyncio
import json
from typing import TYPE_CHECKING, Any, cast

import pytest

from matchlens.config import LLMMode, Settings
from matchlens.llm.client import (
    FoundryLLMClient,
    FoundryResponse,
    LLMDisabledError,
    MockLLMClient,
    create_llm_client,
)

if TYPE_CHECKING:
    from matchlens.models.traces import AgentTrace


class FakeResponse:
    def __init__(self) -> None:
        self.text = '{"keep":true}'
        self.usage_details: dict[str, int] | None = {"input_token_count": 12}


def fake_message(role: str, contents: list[str]) -> dict[str, Any]:
    return {"role": role, "contents": contents}


class FakeFoundryClient:
    def __init__(self, fail_once: bool = False) -> None:
        self.calls = 0
        self.fail_once = fail_once
        self.last_messages: list[Any] = []
        self.last_options: dict[str, Any] = {}

    async def get_response(
        self, messages: list[Any], *, options: dict[str, Any]
    ) -> FoundryResponse:
        self.calls += 1
        self.last_messages = messages
        self.last_options = options
        if self.fail_once and self.calls == 1:
            raise ConnectionError("temporary network failure")
        return FakeResponse()


def test_off_mode_raises_for_agent_fallback() -> None:
    traces: list[AgentTrace] = []
    client = create_llm_client(Settings(llm_mode=LLMMode.OFF), record_trace=traces.append)

    with pytest.raises(LLMDisabledError, match="mode is off for detector"):
        asyncio.run(client.complete_json("detector", "system", "{}", {}, "fast"))

    assert len(traces) == 1
    assert traces[0].status == "fallback"


def test_mock_mode_selects_fixture_by_agent_and_moment_type() -> None:
    response = {"keep": True, "significance": 0.8}
    traces: list[AgentTrace] = []
    client = MockLLMClient({("detector", "goal"): response}, traces.append)

    result = asyncio.run(
        client.complete_json(
            "detector", "instructions", json.dumps({"moment_type": "goal"}), {}, "fast"
        )
    )

    assert result == response
    assert result is not response
    assert len(traces) == 1
    assert traces[0].agent == "detector"
    assert traces[0].status == "ok"
    assert traces[0].action == "complete_json"


def test_mock_mode_uses_default_fixture() -> None:
    client = MockLLMClient({("explainer", "default"): {"headline": "A moment"}})

    result = asyncio.run(client.complete_json("explainer", "system", "not json", {}, "strong"))

    assert result == {"headline": "A moment"}


def test_mock_mode_requires_a_matching_fixture() -> None:
    traces: list[AgentTrace] = []
    client = MockLLMClient({}, traces.append)

    with pytest.raises(LookupError, match="no mock response for detector/goal"):
        asyncio.run(client.complete_json("detector", "system", '{"type":"goal"}', {}, "fast"))

    assert len(traces) == 1
    assert traces[0].status == "error"


@pytest.mark.parametrize("fail_once", [False, True])
def test_foundry_mode_parses_structured_response_and_retries_transport_errors(
    fail_once: bool,
) -> None:
    traces: list[AgentTrace] = []
    client = cast("Any", object.__new__(FoundryLLMClient))
    provider = FakeFoundryClient(fail_once)
    client._client = provider
    client._message_type = fake_message
    client._record_trace = traces.append

    result = asyncio.run(
        client.complete_json("detector", "system", '{"type":"goal"}', {"type": "object"}, "fast")
    )

    assert result == {"keep": True}
    assert provider.calls == (2 if fail_once else 1)
    assert provider.last_options["model"] == "fast"
    assert provider.last_options["response_format"]["json_schema"]["schema"] == {"type": "object"}
    assert traces[0].status == ("retry" if fail_once else "ok")
    assert traces[0].tokens_in == 12
