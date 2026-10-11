import asyncio
import json
from io import StringIO
from typing import TYPE_CHECKING

import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from matchlens.agents.detector import DetectorAgent
from matchlens.config import LLMMode, Settings
from matchlens.llm.client import LLMDisabledError, create_llm_client
from matchlens.models.clock import MatchClock
from matchlens.models.insights import Moment
from matchlens.obs import configure_console_tracing

if TYPE_CHECKING:
    from matchlens.models.traces import AgentTrace


def test_console_span_and_agent_trace_share_trace_id() -> None:
    output = StringIO()
    provider = configure_console_tracing(output)
    assert configure_console_tracing() is provider
    traces: list[AgentTrace] = []
    client = create_llm_client(Settings(llm_mode=LLMMode.OFF), record_trace=traces.append)

    with pytest.raises(LLMDisabledError):
        asyncio.run(
            client.complete_json("detector", "instructions", "{}", {}, "fast", match_id="match-1")
        )

    exported = json.loads(output.getvalue())
    assert exported["name"] == "matchlens.llm.complete_json"
    assert exported["attributes"]["matchlens.agent"] == "detector"
    assert exported["attributes"]["matchlens.result"] == "fallback"
    assert traces[0].trace_id == exported["context"]["trace_id"].removeprefix("0x")
    assert traces[0].status == "fallback"


def test_detector_and_llm_spans_share_parent_trace() -> None:
    exporter = InMemorySpanExporter()
    configure_console_tracing().add_span_processor(SimpleSpanProcessor(exporter))
    moment = Moment(
        moment_id="match-1-1-milestone-h09",
        match_id="match-1",
        type="milestone",
        seq_start=1,
        seq_end=1,
        clock=MatchClock(period=1, ms=1000),
        rule_score=0.3,
        significance=0.3,
        evidence_metric_ids=["player.h09.passes"],
        subject_ids=["h09"],
        source="rule",
    )
    response = {
        "decisions": [{"moment_id": moment.moment_id, "keep": True, "significance": 0.7}],
        "merge_groups": [],
    }
    traces: list[AgentTrace] = []
    client = create_llm_client(
        Settings(llm_mode=LLMMode.MOCK), {("detector", "batch"): response}, traces.append
    )
    detector = DetectorAgent(client, "fast", traces.append)

    result = asyncio.run(detector.evaluate([moment], {}, 15_000))

    spans = {span.name: span for span in exporter.get_finished_spans()}
    review = spans["matchlens.detector.review"]
    llm = spans["matchlens.llm.complete_json"]
    assert len(result) == 1
    assert llm.parent is not None
    assert review.context is not None
    assert llm.context is not None
    assert llm.parent.span_id == review.context.span_id
    assert llm.context.trace_id == review.context.trace_id
    assert all(item.trace_id == f"{review.context.trace_id:032x}" for item in traces)
