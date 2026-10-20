import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from matchlens.agents.live import LiveAgentWorkflow
from matchlens.agents.workflow import MomentResult, WorkflowServices, insight_workflow
from matchlens.config import LLMMode
from matchlens.llm.runtime import RuntimeLLMClient
from matchlens.profiles import DEFAULT_PROFILES
from matchlens.store.memory import MemoryMetricStore
from support.agent_workflow import goal_work, metadata, settings

if TYPE_CHECKING:
    from matchlens.models.traces import AgentTrace


@pytest.mark.parametrize("mode", [LLMMode.MOCK, LLMMode.OFF])
def test_framework_workflow_verifies_and_personalizes_all_profiles(mode: LLMMode) -> None:
    async def run() -> None:
        traces: list[AgentTrace] = []
        config = settings(mode)
        client = RuntimeLLMClient(config, traces.append)
        workflow = insight_workflow(
            WorkflowServices(client, config, metadata(), DEFAULT_PROFILES, traces.append)
        )
        result = await workflow.run(await goal_work())
        output = result.get_outputs()[0]
        assert isinstance(output, MomentResult)
        assert output.insight.status == ("fallback" if mode is LLMMode.OFF else "verified")
        assert {cue.profile_id for cue in output.cues} == {
            profile.profile_id for profile in DEFAULT_PROFILES
        }
        assert all(cue.provenance.checker.passed for cue in output.cues)
        assert all(cue.trigger_seq == 1 for cue in output.cues)
        spanish = next(cue for cue in output.cues if cue.profile_id == "casual_es")
        assert spanish.language == "es"
        assert len(spanish.body) <= 140
        if mode is LLMMode.OFF:
            assert client.calls == 0
            assert all(cue.data["status"] == "fallback" for cue in output.cues)
            assert all(cue.provenance.model_ids == [] for cue in output.cues)
        else:
            assert output.cues[0].provenance.metric_ids == ["team.home.goals"]
            assert any(trace.action == "verify" and trace.status == "approved" for trace in traces)

    asyncio.run(run())


def test_injected_claim_is_rejected_before_cues_are_created() -> None:
    async def run() -> None:
        traces: list[AgentTrace] = []
        config = settings().model_copy(update={"fault_inject_rate": 1.0})
        client = RuntimeLLMClient(config, traces.append)
        workflow = insight_workflow(
            WorkflowServices(client, config, metadata(), DEFAULT_PROFILES[:1], traces.append)
        )
        result = await workflow.run(await goal_work())
        output = result.get_outputs()[0]
        assert isinstance(output, MomentResult)
        assert output.insight.attempts == 2
        assert output.insight.claims[0].value == 1
        assert len(output.cues) == 1
        assert any(
            trace.status == "rejected" and "value_mismatch" in trace.detail for trace in traces
        )

    asyncio.run(run())


def test_moment_work_can_arm_a_single_fact_checker_fault() -> None:
    async def run() -> None:
        traces: list[AgentTrace] = []
        config = settings()
        client = RuntimeLLMClient(config, traces.append)
        work = replace(await goal_work(), fault_inject_rate=1.0)
        result = await insight_workflow(
            WorkflowServices(client, config, metadata(), DEFAULT_PROFILES[:1], traces.append)
        ).run(work)
        output = result.get_outputs()[0]

        assert isinstance(output, MomentResult)
        assert output.insight.status == "verified"
        assert output.insight.attempts == 2
        rejected = next(trace for trace in traces if trace.status == "rejected")
        assert rejected.draft_text is not None
        assert "value_mismatch" in rejected.detail
        assert sum(trace.action == "inject" for trace in traces) == 1

    asyncio.run(run())


def test_switching_llm_off_and_call_budget_preserve_verified_fallbacks() -> None:
    async def run() -> None:
        traces: list[AgentTrace] = []
        config = settings().model_copy(update={"max_llm_calls_per_match": 1})
        client = RuntimeLLMClient(config, traces.append)
        services = WorkflowServices(client, config, metadata(), DEFAULT_PROFILES, traces.append)
        first = (await insight_workflow(services).run(await goal_work())).get_outputs()[0]
        assert isinstance(first, MomentResult)
        assert first.insight.status == "verified"
        assert all(cue.data["status"] == "fallback" for cue in first.cues)
        assert client.calls == 1
        second = (await insight_workflow(services).run(await goal_work())).get_outputs()[0]
        assert isinstance(second, MomentResult)
        assert second.insight.status == "fallback"
        assert len(second.cues) == 4
        assert client.calls == 1
        assert client.mode is LLMMode.OFF
        guard = next(trace for trace in traces if trace.action == "cost_guard")
        assert guard.status == "fallback"
        assert "MAX_LLM_CALLS_PER_MATCH=1" in guard.detail

    asyncio.run(run())


def test_live_generation_retains_the_exact_evidence_view_for_inspection() -> None:
    async def run() -> None:
        work = await goal_work()
        workflow = LiveAgentWorkflow(
            metadata(), DEFAULT_PROFILES, settings(), MemoryMetricStore(), lambda _: None
        )
        try:
            # Exercise archive retention independently of the live scheduling clock.
            result = await workflow._generate(work)  # pyright: ignore[reportPrivateUsage]
            assert result is not None
            anchor = workflow.evidence[result.insight.insight_id]
            assert anchor.moment == work.moment
            assert anchor.insight == result.insight
            assert anchor.store is work.store
        finally:
            await workflow.close()

    asyncio.run(run())
