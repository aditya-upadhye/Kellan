from __future__ import annotations

import asyncio
import json
import re
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


def parts(template: str) -> list[dict[str, str | None]]:
    pieces: list[dict[str, str | None]] = []
    position = 0
    for reference in re.finditer(r"\{([^{}]*)\}", template):
        pieces.append(
            {"text": template[position : reference.start()], "evidence_key": reference.group(1)}
        )
        position = reference.end()
    pieces.append({"text": template[position:], "evidence_key": None})
    return pieces


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


def draft(body: str = "Expected goals reaches {A}.") -> dict[str, Any]:
    return {"headline": "A goal changes the match", "body": parts(body), "tags": ["goal"]}


WRONG = "Expected goals reaches 0.8 xG."


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
    result, traces, errors = run(MockLLMClient({("explainer", "goal"): draft()}))

    assert result.status == "verified"
    assert result.attempts == 1
    assert errors == []
    assert [(trace.action, trace.status) for trace in traces] == [("verify", "approved")]


def test_card_without_metric_evidence_can_verify_on_first_draft() -> None:
    async def process() -> tuple[Insight, list[str]]:
        card = moment().model_copy(
            update={"moment_id": "checker-card", "type": "card", "evidence_metric_ids": []}
        )
        store = MemoryMetricStore()
        response = {
            "headline": "A card changes the contest",
            "body": parts("The booking forces the team to adjust its defensive approach."),
            "tags": ["card"],
        }
        checker = FactCheckerAgent(
            ExplainerAgent(MockLLMClient({("explainer", "card"): response}), "strong"),
            store,
            fault_inject_rate=0.0,
        )
        result = await checker.create_insight(
            card, [], {"home": 0, "away": 0}, {"home": "Kestrel", "away": "Ashmoor"}, []
        )
        errors = await verify_claims(result, card, store)
        return result, [error.code for error in errors]

    result, errors = asyncio.run(process())

    assert result.status == "verified"
    assert result.attempts == 1
    assert result.claims == []
    assert errors == []


def test_retry_receives_error_codes_and_approves_revision() -> None:
    calls: list[dict[str, Any]] = []

    def respond(user: str) -> dict[str, Any]:
        calls.append(json.loads(user))
        return draft(WRONG if len(calls) == 1 else "Expected goals reaches {A}.")

    result, traces, errors = run(MockLLMClient({("explainer", "goal"): respond}))

    assert result.status == "verified"
    assert result.attempts == 2
    assert errors == []
    assert result.body == "Expected goals reaches 0.70 xG."
    assert calls[0]["check_errors"] == []
    assert calls[0]["previous_draft"] is None
    assert calls[1]["check_errors"] == [
        {"code": "uncited_number", "offending_text": "0.8 xG", "location": "body"},
        {"code": "unsupported_claim", "reason": "evidence_required"},
    ]
    assert calls[1]["previous_draft"] == {
        "headline": "A goal changes the match",
        "body": WRONG,
        "facts": [],
    }
    assert "as_of_seq" not in json.dumps(calls[1])
    assert "team.home.xg" not in json.dumps(calls[1])
    assert [(trace.action, trace.status) for trace in traces] == [
        ("verify", "rejected"),
        ("revise", "retry"),
        ("verify", "approved"),
    ]


def test_retry_shows_rendered_facts_of_previous_draft() -> None:
    calls: list[dict[str, Any]] = []

    def respond(user: str) -> dict[str, Any]:
        calls.append(json.loads(user))
        if len(calls) == 1:
            return draft("Expected goals reaches {A} in the second spell.")
        return draft()

    result, _, errors = run(MockLLMClient({("explainer", "goal"): respond}))

    assert result.status == "verified"
    assert errors == []
    assert calls[1]["previous_draft"]["body"].startswith("Expected goals reaches 0.70 xG in")
    assert calls[1]["previous_draft"]["facts"] == [{"evidence_key": "A", "shown_as": "0.70 xG"}]
    assert calls[1]["check_errors"] == [
        {"code": "uncited_number", "offending_text": "second", "location": "body"}
    ]


def test_hand_typed_value_is_rejected_even_when_correct() -> None:
    calls: list[dict[str, Any]] = []

    def respond(user: str) -> dict[str, Any]:
        calls.append(json.loads(user))
        return draft("Expected goals reaches 0.70 xG." if len(calls) == 1 else "Reading {A}.")

    result, _, errors = run(MockLLMClient({("explainer", "goal"): respond}))

    assert result.status == "verified"
    assert result.attempts == 2
    assert errors == []
    assert calls[1]["check_errors"] == [
        {"code": "uncited_number", "offending_text": "0.70 xG", "location": "body"},
        {"code": "unsupported_claim", "reason": "evidence_required"},
    ]


def test_retry_identifies_scoreline_typed_in_free_text() -> None:
    calls: list[dict[str, Any]] = []

    def respond(user: str) -> dict[str, Any]:
        calls.append(json.loads(user))
        return draft("Kestrel leads 2-0." if len(calls) == 1 else "Expected goals reaches {A}.")

    result, _, errors = run(MockLLMClient({("explainer", "goal"): respond}))

    assert result.status == "verified"
    assert errors == []
    assert [
        error["offending_text"] for error in calls[1]["check_errors"] if "offending_text" in error
    ] == ["2", "0"]


def test_retry_removes_uncited_clock_and_ordinal() -> None:
    calls: list[dict[str, Any]] = []

    def respond(user: str) -> dict[str, Any]:
        calls.append(json.loads(user))
        if len(calls) == 1:
            return draft("At 1:23 in the first half, expected goals reaches {A}.")
        return draft()

    result, traces, errors = run(MockLLMClient({("explainer", "goal"): respond}))

    assert result.status == "verified"
    assert result.attempts == 2
    assert errors == []
    assert [error["code"] for error in calls[1]["check_errors"]] == ["uncited_number"] * 3
    assert [error["offending_text"] for error in calls[1]["check_errors"]] == ["1", "23", "first"]
    assert all(error["location"] == "body" for error in calls[1]["check_errors"])
    assert "position" not in json.dumps(calls[1]["check_errors"])
    assert [(trace.action, trace.status) for trace in traces] == [
        ("verify", "rejected"),
        ("revise", "retry"),
        ("verify", "approved"),
    ]


def test_retry_identifies_uncited_number_word_in_headline() -> None:
    calls: list[dict[str, Any]] = []

    def respond(user: str) -> dict[str, Any]:
        calls.append(json.loads(user))
        response = draft()
        if len(calls) == 1:
            response["headline"] = "A second goal changes the match"
        return response

    result, _, errors = run(MockLLMClient({("explainer", "goal"): respond}))

    assert result.status == "verified"
    assert errors == []
    assert calls[1]["check_errors"] == [
        {"code": "uncited_number", "offending_text": "second", "location": "headline"}
    ]


def test_retry_identifies_invalid_evidence_reference() -> None:
    calls: list[dict[str, Any]] = []

    def respond(user: str) -> dict[str, Any]:
        calls.append(json.loads(user))
        return draft(
            "Expected goals reaches {Z}." if len(calls) == 1 else "Expected goals reaches {A}."
        )

    result, _, errors = run(MockLLMClient({("explainer", "goal"): respond}))

    assert result.status == "verified"
    assert errors == []
    assert calls[1]["check_errors"] == [
        {
            "code": "unsupported_claim",
            "reason": "invalid_evidence_reference",
            "offending_text": "{Z}",
        },
        {"code": "unsupported_claim", "reason": "evidence_required"},
    ]


def test_persistently_invalid_reference_never_ships_verified() -> None:
    result, traces, errors = run(
        MockLLMClient({("explainer", "goal"): draft("Expected goals reaches {Z}.")})
    )

    assert result.status == "fallback"
    assert "{" not in result.body
    assert errors == []
    assert sum(trace.status == "rejected" for trace in traces) == 3


def test_retry_identifies_unit_typed_after_count_reference() -> None:
    calls: list[dict[str, Any]] = []
    goals = evidence().model_copy(
        update={"metric_id": "team.home.goals", "label": "Goals", "value": 2.0, "unit": "count"}
    )
    scoring = moment().model_copy(update={"evidence_metric_ids": [goals.metric_id]})

    def respond(user: str) -> dict[str, Any]:
        calls.append(json.loads(user))
        return draft("Kestrel have {A} points." if len(calls) == 1 else "Kestrel have {A} goals.")

    async def process() -> Insight:
        store = MemoryMetricStore()
        await store.put("checker-match", goals)
        checker = FactCheckerAgent(
            ExplainerAgent(MockLLMClient({("explainer", "goal"): respond}), "strong"),
            store,
            fault_inject_rate=0.0,
        )
        return await checker.create_insight(
            scoring, [goals], {"home": 2, "away": 0}, {"home": "Kestrel"}, []
        )

    result = asyncio.run(process())

    assert result.status == "verified"
    assert result.attempts == 2
    assert calls[1]["check_errors"] == [
        {"code": "uncited_number", "offending_text": "2 points", "location": "body"}
    ]


def test_exhausted_retries_use_verified_template() -> None:
    calls = 0

    def respond(user: str) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return draft(WRONG)

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
    result, traces, errors = run(MockLLMClient({("explainer", "goal"): {"body": parts("missing")}}))

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
        return draft()

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
    assert traces[1].draft_text is not None
    assert "Expected goals" in traces[1].draft_text


def test_fault_injection_still_falls_back_if_revisions_are_wrong() -> None:
    result, traces, errors = run(
        MockLLMClient({("explainer", "goal"): draft("Expected goals reaches {A}, not 0.8 xG.")}),
        fault_inject_rate=1.0,
    )

    assert result.status == "fallback"
    assert result.attempts == 3
    assert errors == []
    assert sum(trace.action == "inject" for trace in traces) == 1
    assert sum(trace.status == "rejected" for trace in traces) == 3


def test_zero_fault_rate_preserves_approved_draft() -> None:
    result, traces, errors = run(
        MockLLMClient({("explainer", "goal"): draft()}), fault_inject_rate=0.0
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


def test_prose_only_draft_is_rejected_when_evidence_is_supplied() -> None:
    calls: list[dict[str, Any]] = []

    def respond(user: str) -> dict[str, Any]:
        calls.append(json.loads(user))
        return draft("The pressure is clearly building." if len(calls) == 1 else "Reading {A}.")

    result, _, errors = run(MockLLMClient({("explainer", "goal"): respond}))

    assert result.status == "verified"
    assert result.attempts == 2
    assert errors == []
    assert [claim.metric_id for claim in result.claims] == ["team.home.xg"]
    assert calls[1]["check_errors"] == [
        {"code": "unsupported_claim", "reason": "evidence_required"}
    ]


def test_persistent_prose_only_draft_falls_back_to_cited_template() -> None:
    result, traces, errors = run(
        MockLLMClient({("explainer", "goal"): draft("The pressure is clearly building.")})
    )

    assert result.status == "fallback"
    assert [claim.metric_id for claim in result.claims] == ["team.home.xg"]
    assert errors == []
    assert sum(trace.status == "rejected" for trace in traces) == 3
    assert all(
        "unsupported_claim" in trace.detail for trace in traces if trace.status == "rejected"
    )


def test_typed_value_then_prose_only_then_cited_metric() -> None:
    calls: list[dict[str, Any]] = []
    momentum = evidence().model_copy(
        update={
            "metric_id": "match.momentum",
            "scope": "match",
            "subject_id": None,
            "label": "Momentum",
            "value": -39.2102,
            "unit": "index",
        }
    )
    swing = moment().model_copy(
        update={"type": "momentum_swing", "evidence_metric_ids": [momentum.metric_id]}
    )
    bodies = [
        "Momentum swings to -39.2 index.",
        "Momentum swings sharply toward the away side.",
        "Momentum swings to {A} toward the away side.",
    ]

    def respond(user: str) -> dict[str, Any]:
        calls.append(json.loads(user))
        return draft(bodies[len(calls) - 1])

    async def process() -> tuple[Insight, list[str]]:
        store = MemoryMetricStore()
        await store.put("checker-match", momentum)
        checker = FactCheckerAgent(
            ExplainerAgent(MockLLMClient({("explainer", "momentum_swing"): respond}), "strong"),
            store,
            fault_inject_rate=0.0,
        )
        result = await checker.create_insight(
            swing, [momentum], {"home": 0, "away": 0}, {"home": "Kestrel"}, []
        )
        return result, [error.code for error in await verify_claims(result, swing, store)]

    result, codes = asyncio.run(process())

    assert result.status == "verified"
    assert result.attempts == 3
    assert codes == []
    assert result.body == "Momentum swings to -39.2 index toward the away side."
    assert [error["code"] for error in calls[1]["check_errors"]] == [
        "uncited_number",
        "unsupported_claim",
    ]
    assert calls[2]["check_errors"] == [
        {"code": "unsupported_claim", "reason": "evidence_required"}
    ]
