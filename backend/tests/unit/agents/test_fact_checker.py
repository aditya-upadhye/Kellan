from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest

from matchlens.agents.explainer import ExplainerAgent
from matchlens.agents.fact_checker import FactCheckerAgent
from matchlens.agents.verifier import verify_claims
from matchlens.llm.client import MockLLMClient, OffLLMClient
from matchlens.models.clock import MatchClock
from matchlens.models.insights import Insight, Moment
from matchlens.models.metrics import MetricSnapshot
from matchlens.store.memory import MemoryMetricStore

if TYPE_CHECKING:
    from matchlens.models.traces import AgentTrace


def moment() -> Moment:
    return Moment(
        moment_id="checker-moment",
        match_id="checker-match",
        type="goal",
        seq_start=10,
        seq_end=10,
        clock=MatchClock(period=1, ms=10_000),
        rule_score=1.0,
        significance=1.0,
        evidence_metric_ids=["team.home.xg"],
        subject_ids=["home"],
        source="rule",
    )


def evidence(label: str = "Expected goals") -> MetricSnapshot:
    return MetricSnapshot(
        metric_id="team.home.xg",
        scope="team",
        subject_id="home",
        label=label,
        value=0.7,
        unit="xG",
        window="match",
        as_of_seq=10,
        clock=MatchClock(period=1, ms=10_000),
    )


def draft(value: float) -> dict[str, Any]:
    return {
        "headline": "A goal changes the match",
        "body": "Expected goals reaches 0.7 xG.",
        "claims": [
            {
                "text_span": "0.7 xG",
                "metric_id": "team.home.xg",
                "value": value,
                "as_of_seq": 10,
            }
        ],
        "tags": ["goal"],
    }


def run(
    client: MockLLMClient | OffLLMClient,
    snapshots: list[MetricSnapshot] | None = None,
    fault_inject_rate: float = 0.0,
) -> tuple[Insight, list[AgentTrace], list[str]]:
    async def process() -> tuple[Insight, list[AgentTrace], list[str]]:
        store = MemoryMetricStore()
        for snapshot in snapshots if snapshots is not None else [evidence()]:
            await store.put("checker-match", snapshot)
        traces: list[AgentTrace] = []
        checker = FactCheckerAgent(
            ExplainerAgent(client, "strong"),
            store,
            traces.append,
            fault_inject_rate=fault_inject_rate,
        )
        result = await checker.create_insight(
            moment(), [evidence()], {"home": 1, "away": 0}, {"home": "Kestrel"}, []
        )
        errors = await verify_claims(result, moment(), store)
        return result, traces, [error.code for error in errors]

    return asyncio.run(process())


def test_approved_first_draft() -> None:
    result, traces, errors = run(MockLLMClient({("explainer", "goal"): draft(0.7)}))

    assert result.status == "verified"
    assert result.attempts == 1
    assert errors == []
    assert [(trace.action, trace.status) for trace in traces] == [("verify", "approved")]


def test_retry_receives_error_codes_and_approves_revision() -> None:
    calls: list[dict[str, Any]] = []

    def respond(user: str) -> dict[str, Any]:
        calls.append(json.loads(user))
        return draft(0.8 if len(calls) == 1 else 0.7)

    result, traces, errors = run(MockLLMClient({("explainer", "goal"): respond}))

    assert result.status == "verified"
    assert result.attempts == 2
    assert errors == []
    assert calls[0]["check_errors"] == []
    assert calls[1]["check_errors"][0]["code"] == "value_mismatch"
    assert [(trace.action, trace.status) for trace in traces] == [
        ("verify", "rejected"),
        ("revise", "retry"),
        ("verify", "approved"),
    ]


def test_exhausted_retries_use_verified_template() -> None:
    calls = 0

    def respond(user: str) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return draft(0.8)

    result, traces, errors = run(MockLLMClient({("explainer", "goal"): respond}))

    assert calls == 3
    assert result.status == "fallback"
    assert result.attempts == 3
    assert result.claims[0].value == 0.7
    assert errors == []
    assert [trace.status for trace in traces] == [
        "rejected",
        "retry",
        "rejected",
        "retry",
        "rejected",
        "fallback",
    ]


def test_off_mode_falls_back_without_retry() -> None:
    result, traces, errors = run(OffLLMClient())

    assert result.status == "fallback"
    assert result.attempts == 1
    assert errors == []
    assert [(trace.action, trace.status) for trace in traces] == [("template", "fallback")]


def test_invalid_model_response_falls_back() -> None:
    result, traces, errors = run(MockLLMClient({("explainer", "goal"): {"body": "missing"}}))

    assert result.status == "fallback"
    assert errors == []
    assert [(trace.action, trace.status) for trace in traces] == [
        ("draft", "error"),
        ("template", "fallback"),
    ]


def test_template_omits_unverifiable_evidence() -> None:
    result, _, errors = run(OffLLMClient(), [])

    assert result.status == "fallback"
    assert result.claims == []
    assert errors == []


def test_template_ignores_label_containing_uncited_number() -> None:
    result, _, errors = run(OffLLMClient(), [evidence("Top 2 chances")])

    assert result.status == "fallback"
    assert result.claims == []
    assert errors == []


def test_fault_injection_is_rejected_then_revision_is_approved() -> None:
    calls: list[dict[str, Any]] = []

    def respond(user: str) -> dict[str, Any]:
        calls.append(json.loads(user))
        return draft(0.7)

    result, traces, errors = run(
        MockLLMClient({("explainer", "goal"): respond}), fault_inject_rate=1.0
    )

    assert result.status == "verified"
    assert result.attempts == 2
    assert result.claims[0].value == 0.7
    assert errors == []
    assert calls[1]["check_errors"][0]["code"] == "value_mismatch"
    assert [(trace.action, trace.status) for trace in traces] == [
        ("inject", "ok"),
        ("verify", "rejected"),
        ("revise", "retry"),
        ("verify", "approved"),
    ]
    assert "value_mismatch" in traces[1].detail


def test_fault_injection_still_falls_back_if_revisions_are_wrong() -> None:
    result, traces, errors = run(
        MockLLMClient({("explainer", "goal"): draft(0.8)}), fault_inject_rate=1.0
    )

    assert result.status == "fallback"
    assert result.attempts == 3
    assert errors == []
    assert sum(trace.action == "inject" for trace in traces) == 1
    assert sum(trace.status == "rejected" for trace in traces) == 3


def test_zero_fault_rate_preserves_approved_draft() -> None:
    result, traces, errors = run(
        MockLLMClient({("explainer", "goal"): draft(0.7)}), fault_inject_rate=0.0
    )

    assert result.status == "verified"
    assert result.attempts == 1
    assert errors == []
    assert all(trace.action != "inject" for trace in traces)


@pytest.mark.parametrize("rate", [-0.1, 1.1])
def test_fault_rate_must_be_in_range(rate: float) -> None:
    with pytest.raises(ValueError, match="fault_inject_rate"):
        FactCheckerAgent(
            ExplainerAgent(OffLLMClient(), "strong"),
            MemoryMetricStore(),
            fault_inject_rate=rate,
        )
