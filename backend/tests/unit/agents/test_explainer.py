from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from matchlens.agents.explainer import ExplainerAgent
from matchlens.llm.client import LLMDisabledError, MockLLMClient, OffLLMClient
from matchlens.models.clock import MatchClock
from matchlens.models.insights import Insight, Moment
from matchlens.models.metrics import MetricSnapshot

if TYPE_CHECKING:
    from collections.abc import Mapping

    from matchlens.models.base import TeamSide


def moment() -> Moment:
    return Moment(
        moment_id="match-1-45-goal-h09",
        match_id="match-1",
        type="goal",
        seq_start=45,
        seq_end=45,
        clock=MatchClock(period=2, ms=15 * 60_000),
        rule_score=1.0,
        significance=1.0,
        evidence_metric_ids=["team.home.xg"],
        subject_ids=["h09"],
        source="rule",
    )


def evidence() -> MetricSnapshot:
    return MetricSnapshot(
        metric_id="team.home.xg",
        scope="team",
        subject_id="home",
        label="Expected goals",
        value=0.7,
        unit="xG",
        window="match",
        as_of_seq=45,
        clock=MatchClock(period=2, ms=15 * 60_000),
    )


def prior_insight(index: int) -> Insight:
    return Insight(
        insight_id=f"prior-{index}",
        moment_id=f"prior-moment-{index}",
        headline=f"Headline {index}",
        body=f"Body {index}",
        claims=[],
        tags=[],
        status="verified",
        attempts=1,
        errors=[],
    )


def explain(
    agent: ExplainerAgent,
    snapshots: list[MetricSnapshot] | None = None,
    score: Mapping[TeamSide, int] | None = None,
) -> Insight:
    return asyncio.run(
        agent.explain(
            moment(),
            [evidence()] if snapshots is None else snapshots,
            {"home": 1, "away": 0} if score is None else score,
            {"home": "Kestrel Bay Athletic", "h09": "Amir Vale"},
            [prior_insight(index) for index in range(4)],
        )
    )


def test_explainer_returns_structured_draft_with_claims_and_context() -> None:
    captured: list[dict[str, Any]] = []

    def respond(user: str) -> dict[str, Any]:
        captured.append(json.loads(user))
        return {
            "headline": "Kestrel seize the lead",
            "body": "Their xG reaches 0.7 as the pressure pays off.",
            "claims": [
                {
                    "text_span": "0.7",
                    "metric_id": "team.home.xg",
                    "value": 0.7,
                    "as_of_seq": 45,
                }
            ],
            "tags": ["goal", "pressure"],
        }

    agent = ExplainerAgent(MockLLMClient({("explainer", "goal"): respond}), "strong")
    draft = explain(agent)

    assert draft.status == "draft"
    assert draft.attempts == 1
    assert draft.errors == []
    assert draft.moment_id == moment().moment_id
    assert draft.claims[0].claim_id.startswith(draft.insight_id)
    assert draft.claims[0].metric_id == "team.home.xg"
    assert draft.claims[0].text_span == "0.7"
    assert captured[0]["score"] == {"home": 1, "away": 0}
    assert captured[0]["minute"] == 60
    assert captured[0]["names"]["h09"] == "Amir Vale"
    assert captured[0]["evidence"][0]["as_of_seq"] == 45
    assert [item["headline"] for item in captured[0]["recent_insights"]] == [
        "Headline 1",
        "Headline 2",
        "Headline 3",
    ]


def test_explainer_rejects_invalid_response_shape() -> None:
    agent = ExplainerAgent(
        MockLLMClient({("explainer", "goal"): {"headline": "Only a headline"}}), "strong"
    )

    with pytest.raises(ValidationError):
        explain(agent)


def test_explainer_rejects_unrelated_evidence_and_invalid_score() -> None:
    agent = ExplainerAgent(OffLLMClient(), "strong")
    unrelated = evidence().model_copy(update={"metric_id": "team.away.xg", "subject_id": "away"})

    with pytest.raises(ValueError, match="outside the moment"):
        explain(agent, snapshots=[unrelated])
    with pytest.raises(ValueError, match="score must contain"):
        explain(agent, score={"home": -1, "away": 0})


def test_explainer_leaves_off_mode_for_fallback_checkpoint() -> None:
    agent = ExplainerAgent(OffLLMClient(), "strong")

    with pytest.raises(LLMDisabledError):
        explain(agent)
