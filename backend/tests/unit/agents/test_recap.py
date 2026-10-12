import asyncio
from typing import TYPE_CHECKING

from matchlens.agents.recap import RecapAgent
from matchlens.llm.runtime import RuntimeLLMClient
from matchlens.models.clock import MatchClock
from matchlens.models.metrics import MetricSnapshot
from matchlens.profiles import DEFAULT_PROFILES
from matchlens.store.memory import MemoryMetricStore
from support.agent_workflow import settings

if TYPE_CHECKING:
    from matchlens.models.traces import AgentTrace


def test_recap_uses_strong_model_and_verifies_snapshot_claims() -> None:
    async def run() -> None:
        traces: list[AgentTrace] = []
        config = settings()
        client = RuntimeLLMClient(config, traces.append)
        store = MemoryMetricStore()
        snapshot = MetricSnapshot(
            metric_id="team.home.goals",
            scope="team",
            subject_id="home",
            label="Home goals",
            value=1,
            unit="count",
            window="match",
            as_of_seq=10,
            clock=MatchClock(period=1, ms=2_700_000),
        )
        await store.put("match-a", snapshot)
        recap = await RecapAgent(client, "strong-model", "match-a", traces.append).create_recap(
            "half", DEFAULT_PROFILES[0], [], [snapshot], store.snapshot()
        )

        assert recap.kind == "half"
        assert recap.status == "verified"
        assert len(recap.paragraphs) == 3
        assert recap.claims[0].metric_id == "team.home.goals"
        assert recap.claims[0].as_of_seq == 10
        assert any(trace.action == "verify" and trace.status == "approved" for trace in traces)
        assert client.calls == 1

    asyncio.run(run())


def test_recap_off_mode_returns_verified_qualitative_fallback() -> None:
    async def run() -> None:
        config = settings().model_copy(update={"llm_mode": "off"})
        traces: list[AgentTrace] = []
        store = MemoryMetricStore()
        recap = await RecapAgent(
            RuntimeLLMClient(config, traces.append), "strong-model", "match-a", traces.append
        ).create_recap("full", DEFAULT_PROFILES[2], [], [], store.snapshot())

        assert recap.status == "fallback"
        assert len(recap.paragraphs) == 3
        assert recap.claims == []
        assert all("The " not in paragraph for paragraph in recap.paragraphs)

    asyncio.run(run())
