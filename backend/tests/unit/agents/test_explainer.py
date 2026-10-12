from __future__ import annotations

import asyncio
import json
import re
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from matchlens.agents.explainer import ExplainerAgent, ExplainerResponse
from matchlens.agents.facts import render_fact
from matchlens.agents.verifier import verify_claims
from matchlens.llm.client import LLMDisabledError, MockLLMClient, OffLLMClient
from matchlens.models.clock import MatchClock
from matchlens.models.insights import Insight, Moment
from matchlens.models.metrics import MetricSnapshot
from matchlens.store.memory import MemoryMetricStore

if TYPE_CHECKING:
    from collections.abc import Mapping

    from matchlens.models.base import TeamSide


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
            "body": parts("Their expected goals reach {A} as the pressure pays off."),
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
    assert draft.body == "Their expected goals reach 0.70 xG as the pressure pays off."
    assert draft.claims[0].text_span == "0.70 xG"
    assert draft.claims[0].value == 0.7
    assert draft.claims[0].as_of_seq == 45
    assert captured[0]["leader"] == "Kestrel Bay Athletic"
    assert captured[0]["subjects"] == [{"name": "Amir Vale", "team": "Kestrel Bay Athletic"}]
    assert captured[0]["evidence"] == [
        {
            "key": "A",
            "label": "Expected goals",
            "value": 0.7,
            "unit": "xG",
            "shown_as": "0.70 xG",
            "subject": {"name": "Kestrel Bay Athletic", "team": "Kestrel Bay Athletic"},
        }
    ]
    assert "moment" not in captured[0]
    assert "score" not in captured[0]
    assert "minute" not in captured[0]
    assert "as_of_seq" not in json.dumps(captured[0])
    assert captured[0]["recent_topics"] == [[], [], []]


def test_explainer_supplies_away_player_affiliation() -> None:
    captured: list[dict[str, Any]] = []

    def respond(user: str) -> dict[str, Any]:
        captured.append(json.loads(user))
        return {
            "headline": "A player receives a card",
            "body": parts("Elias Thornquist receives a card."),
            "tags": ["card"],
        }

    card = moment().model_copy(
        update={"type": "card", "subject_ids": ["a10"], "evidence_metric_ids": []}
    )
    agent = ExplainerAgent(MockLLMClient({("explainer", "card"): respond}), "strong")

    asyncio.run(
        agent.explain(
            card,
            [],
            {"home": 0, "away": 0},
            {
                "home": "Vellmont City",
                "away": "Kestrel Bay Athletic",
                "a10": "Elias Thornquist",
            },
            [],
        )
    )

    assert captured[0]["subjects"] == [{"name": "Elias Thornquist", "team": "Kestrel Bay Athletic"}]


def test_explainer_cites_three_metrics_with_correct_subjects() -> None:
    captured: list[dict[str, Any]] = []
    away_possession = evidence().model_copy(
        update={
            "metric_id": "team.away.possession_pct",
            "subject_id": "away",
            "label": "Possession",
            "value": 46.1438,
            "unit": "%",
        }
    )
    momentum = MetricSnapshot(
        metric_id="match.momentum",
        scope="match",
        subject_id=None,
        label="Momentum",
        value=-15.0295,
        unit="index",
        window="match",
        as_of_seq=45,
        clock=MatchClock(period=2, ms=15 * 60_000),
    )
    control_index = momentum.model_copy(
        update={
            "metric_id": "match.control_index",
            "label": "Control index",
            "value": -30.4348,
        }
    )
    goal = moment().model_copy(
        update={
            "evidence_metric_ids": [
                "team.home.xg",
                away_possession.metric_id,
                momentum.metric_id,
                control_index.metric_id,
            ]
        }
    )

    def respond(user: str) -> dict[str, Any]:
        captured.append(json.loads(user))
        return {
            "headline": "Both clubs shape the attack",
            "body": parts(
                "Kestrel Bay Athletic has {A}, Vellmont City holds {B} possession, "
                "momentum is {C}, and control is chaos at {D}."
            ),
            "tags": ["goal"],
        }

    async def process() -> tuple[Insight, list[Any]]:
        store = MemoryMetricStore()
        await store.put(goal.match_id, evidence())
        await store.put(goal.match_id, away_possession)
        await store.put(goal.match_id, momentum)
        await store.put(goal.match_id, control_index)
        agent = ExplainerAgent(MockLLMClient({("explainer", "goal"): respond}), "strong")
        draft = await agent.explain(
            goal,
            [evidence(), away_possession, momentum, control_index],
            {"home": 1, "away": 0},
            {"home": "Kestrel Bay Athletic", "away": "Vellmont City", "h09": "Amir Vale"},
            [],
        )
        return draft, await verify_claims(draft, goal, store)

    draft, errors = asyncio.run(process())

    assert errors == []
    assert [(claim.metric_id, claim.value) for claim in draft.claims] == [
        ("team.home.xg", 0.7),
        ("team.away.possession_pct", 46.1438),
        ("match.momentum", -15.0295),
        ("match.control_index", -30.4348),
    ]
    assert captured[0]["evidence"][1]["subject"] == {
        "name": "Vellmont City",
        "team": "Vellmont City",
    }
    assert captured[0]["evidence"][2]["subject"] is None
    assert captured[0]["evidence"][3]["state"] == "chaos"


def test_explainer_renders_references_and_keeps_other_model_text() -> None:
    response = {
        "headline": "Kestrel seize the lead",
        "body": parts("Their xG reaches {A} (evidence). Pressure pays off."),
        "tags": ["goal"],
    }
    agent = ExplainerAgent(MockLLMClient({("explainer", "goal"): response}), "strong")

    draft = explain(agent)

    assert draft.body == "Their xG reaches 0.70 xG (evidence). Pressure pays off."
    assert [claim.text_span for claim in draft.claims] == ["0.70 xG"]


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


def snapshot(metric_id: str, value: float, unit: str, seq: int = 45) -> MetricSnapshot:
    return MetricSnapshot.model_validate(
        {
            "metric_id": metric_id,
            "scope": metric_id.split(".", maxsplit=1)[0],
            "subject_id": None if metric_id.startswith("match.") else metric_id.split(".")[1],
            "label": "Metric",
            "value": value,
            "unit": unit,
            "window": "match",
            "as_of_seq": seq,
            "clock": MatchClock(period=2, ms=15 * 60_000),
        }
    )


RENDER_CASES = [
    (snapshot("match.momentum", -15.0295, "index"), "-15.0 index"),
    (snapshot("match.momentum", -0.04, "index"), "0.0 index"),
    (snapshot("match.control_index", 30.45, "index"), "30.5 index"),
    (snapshot("team.home.xg", 0.125, "xG"), "0.13 xG"),
    (snapshot("team.home.possession_pct", 46.1438, "%"), "46.1%"),
    (snapshot("team.home.ppda", 8.25, "ratio"), "8.3 ratio"),
    (snapshot("player.h09.top_speed_kmh", 35.96, "km/h"), "36.0 km/h"),
    (snapshot("player.h09.distance_m", 1204.5, "m"), "1204.5 m"),
    (snapshot("team.home.goals", 2.0, "count"), "2"),
]


@pytest.mark.parametrize(("fact", "shown"), RENDER_CASES)
def test_rendered_fact_is_verified_and_cited_exactly(fact: MetricSnapshot, shown: str) -> None:
    assert render_fact(fact) == shown
    cited = moment().model_copy(update={"evidence_metric_ids": [fact.metric_id]})
    noun = " goals" if fact.unit == "count" else ""

    async def process() -> tuple[Insight, list[Any], list[dict[str, Any]]]:
        store = MemoryMetricStore()
        await store.put(cited.match_id, fact)
        captured: list[dict[str, Any]] = []

        def respond(user: str) -> dict[str, Any]:
            captured.append(json.loads(user))
            return {
                "headline": "A pattern stands out",
                "body": parts(f"The reading is {{A}}{noun} right now."),
                "tags": [],
            }

        agent = ExplainerAgent(MockLLMClient({("explainer", "goal"): respond}), "strong")
        draft = await agent.explain(cited, [fact], {"home": 1, "away": 0}, {"home": "Kestrel"}, [])
        return draft, await verify_claims(draft, cited, store), captured

    draft, errors, captured = asyncio.run(process())

    assert errors == []
    assert captured[0]["evidence"][0]["shown_as"] == shown
    assert [(claim.text_span, claim.metric_id, claim.value) for claim in draft.claims] == [
        (shown, fact.metric_id, fact.value)
    ]
    assert draft.body == f"The reading is {shown}{noun} right now."


def test_repeated_reference_creates_one_claim_per_occurrence() -> None:
    response: dict[str, Any] = {
        "headline": "Pressure builds",
        "body": parts("{A} now, {A} again."),
        "tags": [],
    }
    agent = ExplainerAgent(MockLLMClient({("explainer", "goal"): response}), "strong")

    draft = explain(agent)

    assert draft.body == "0.70 xG now, 0.70 xG again."
    assert len(draft.claims) == 2
    assert len({claim.claim_id for claim in draft.claims}) == 2


def verify_codes(response: dict[str, Any]) -> tuple[Insight, list[str]]:
    agent = ExplainerAgent(MockLLMClient({("explainer", "goal"): response}), "strong")

    async def process() -> tuple[Insight, list[str]]:
        store = MemoryMetricStore()
        await store.put("match-1", evidence())
        draft = await agent.explain(
            moment(), [evidence()], {"home": 1, "away": 0}, {"home": "Kestrel"}, []
        )
        return draft, [error.code for error in await verify_claims(draft, moment(), store)]

    return asyncio.run(process())


@pytest.mark.parametrize("reference", ["{Z}", "{a}", "{}", "{AB}", "{0}"])
def test_invalid_reference_is_never_verified(reference: str) -> None:
    draft, codes = verify_codes(
        {"headline": "Pressure builds", "body": parts(f"Reading {reference}."), "tags": []}
    )

    assert draft.claims == []
    assert reference in draft.body
    assert "unsupported_claim" in codes


def test_reference_in_headline_is_never_verified() -> None:
    _, codes = verify_codes(
        {"headline": "Pressure at {A}", "body": parts("The pattern holds."), "tags": []}
    )

    assert codes == ["unsupported_claim"]


@pytest.mark.parametrize(
    "body",
    [
        "Reading {A} after 12 minutes.",
        "Reading {A}, the second spell.",
        "Reading {A} and three chances.",
        "Reading 0.9 xG beside {A}.",
        "Reading {A} with 0.70 xG typed again.",
    ],
)
def test_numbers_written_in_free_text_stay_rejected(body: str) -> None:
    _, codes = verify_codes({"headline": "Pressure builds", "body": parts(body), "tags": []})

    assert "uncited_number" in codes


def test_response_schema_separates_prose_from_evidence_references() -> None:
    schema = ExplainerResponse.model_json_schema()
    part = schema["$defs"]["BodyPart"]

    assert set(schema["properties"]) == {"headline", "body", "tags"}
    assert schema["properties"]["body"]["type"] == "array"
    assert set(part["properties"]) == {"text", "evidence_key"}
    assert set(part["required"]) == {"text", "evidence_key"}


def test_metric_reference_renders_exact_trusted_value_unit_and_claim() -> None:
    momentum = snapshot("match.momentum", -39.2102, "index")
    cited = moment().model_copy(
        update={"type": "momentum_swing", "evidence_metric_ids": [momentum.metric_id]}
    )

    async def process() -> tuple[Insight, list[Any]]:
        store = MemoryMetricStore()
        await store.put(cited.match_id, momentum)
        response = {
            "headline": "Momentum swings hard",
            "body": [
                {"text": "The momentum reading drops to ", "evidence_key": "A"},
                {"text": " as the away side surges.", "evidence_key": None},
            ],
            "tags": ["momentum"],
        }
        agent = ExplainerAgent(MockLLMClient({("explainer", "momentum_swing"): response}), "strong")
        draft = await agent.explain(cited, [momentum], {"home": 0, "away": 0}, {}, [])
        return draft, await verify_claims(draft, cited, store)

    draft, errors = asyncio.run(process())

    assert errors == []
    assert draft.body == "The momentum reading drops to -39.2 index as the away side surges."
    assert [(c.text_span, c.metric_id, c.value, c.as_of_seq) for c in draft.claims] == [
        ("-39.2 index", "match.momentum", -39.2102, 45)
    ]


def test_value_typed_into_prose_is_rejected_even_when_correct() -> None:
    _, codes = verify_codes(
        {
            "headline": "Pressure builds",
            "body": [{"text": "Expected goals reach 0.7 xG.", "evidence_key": None}],
            "tags": [],
        }
    )

    assert codes == ["uncited_number"]


def test_braces_typed_into_prose_are_not_a_reference() -> None:
    draft, codes = verify_codes(
        {
            "headline": "Pressure builds",
            "body": [{"text": "Expected goals reach {A}.", "evidence_key": None}],
            "tags": [],
        }
    )

    assert draft.claims == []
    assert codes == ["unsupported_claim"]


NAMES = {"home": "Kestrel Bay Athletic", "away": "Ashmoor Rovers"}


def swing_moment() -> Moment:
    return moment().model_copy(
        update={
            "type": "momentum_swing",
            "seq_start": 40,
            "seq_end": 45,
            "evidence_metric_ids": ["match.momentum"],
            "subject_ids": [],
        }
    )


def swing_readings(start: float, end: float) -> list[MetricSnapshot]:
    return [
        snapshot("match.momentum", start, "index", 40),
        snapshot("match.momentum", end, "index"),
    ]


def run_swing(
    start: float, end: float, body: list[dict[str, str | None]]
) -> tuple[dict[str, Any], Insight, list[Any]]:
    readings = swing_readings(start, end)
    captured: list[dict[str, Any]] = []

    def respond(user: str) -> dict[str, Any]:
        captured.append(json.loads(user))
        return {"headline": "Momentum swings", "body": body, "tags": ["momentum"]}

    async def process() -> tuple[Insight, list[Any]]:
        store = MemoryMetricStore()
        for reading in readings:
            await store.put("match-1", reading)
        agent = ExplainerAgent(MockLLMClient({("explainer", "momentum_swing"): respond}), "strong")
        draft = await agent.explain(swing_moment(), readings, {"home": 0, "away": 0}, NAMES, [])
        return draft, await verify_claims(draft, swing_moment(), store)

    draft, errors = asyncio.run(process())
    return captured[0], draft, errors


FROM_TO: list[dict[str, str | None]] = [
    {"text": "Momentum moves from", "evidence_key": "A"},
    {"text": "to", "evidence_key": "B"},
    {"text": ".", "evidence_key": None},
]


@pytest.mark.parametrize(
    ("start", "end", "toward", "end_favours"),
    [
        (-72.0, -39.2102, "Kestrel Bay Athletic", "Ashmoor Rovers"),
        (30.0, -39.2102, "Ashmoor Rovers", "Ashmoor Rovers"),
        (-30.0, 12.5, "Kestrel Bay Athletic", "Kestrel Bay Athletic"),
        (72.0, 31.5, "Ashmoor Rovers", "Kestrel Bay Athletic"),
    ],
)
def test_swing_direction_comes_from_the_change_not_the_end_sign(
    start: float, end: float, toward: str, end_favours: str
) -> None:
    request, _, _ = run_swing(start, end, FROM_TO)

    context = request["momentum"]
    assert context["change_toward"] == toward
    assert context["readings"][1]["favours"] == end_favours
    assert context["positive_favours"] == "Kestrel Bay Athletic"
    assert context["negative_favours"] == "Ashmoor Rovers"
    assert [(item["key"], item["phase"]) for item in request["evidence"]] == [
        ("A", "start"),
        ("B", "end"),
    ]


def test_swing_renders_both_readings_as_exact_claims_with_spacing() -> None:
    _, draft, errors = run_swing(-72.0, -39.2102, FROM_TO)

    assert errors == []
    assert draft.body == "Momentum moves from -72.0 index to -39.2 index."
    assert [(c.text_span, c.value, c.as_of_seq) for c in draft.claims] == [
        ("-72.0 index", -72.0, 40),
        ("-39.2 index", -39.2102, 45),
    ]


def test_swing_number_typed_in_prose_is_still_rejected() -> None:
    body: list[dict[str, str | None]] = [
        {"text": "Momentum moves from", "evidence_key": "A"},
        {"text": "to -39.2 index.", "evidence_key": None},
    ]

    _, _, errors = run_swing(-72.0, -39.2102, body)

    assert [error.code for error in errors] == ["uncited_number"]


def test_momentum_context_is_absent_without_momentum_evidence() -> None:
    captured: list[dict[str, Any]] = []

    def respond(user: str) -> dict[str, Any]:
        captured.append(json.loads(user))
        return {"headline": "A goal", "body": parts("Reading {A}."), "tags": []}

    explain(ExplainerAgent(MockLLMClient({("explainer", "goal"): respond}), "strong"))

    assert captured[0]["momentum"] is None


def test_goal_momentum_reading_names_sides_without_a_change() -> None:
    reading = snapshot("match.momentum", -39.2102, "index")
    goal = moment().model_copy(update={"evidence_metric_ids": ["match.momentum"]})
    captured: list[dict[str, Any]] = []

    def respond(user: str) -> dict[str, Any]:
        captured.append(json.loads(user))
        return {"headline": "A goal", "body": parts("Reading {A}."), "tags": []}

    agent = ExplainerAgent(MockLLMClient({("explainer", "goal"): respond}), "strong")
    asyncio.run(agent.explain(goal, [reading], {"home": 1, "away": 0}, NAMES, []))

    assert "change_toward" not in captured[0]["momentum"]
    assert captured[0]["momentum"]["readings"] == [{"key": "A", "favours": "Ashmoor Rovers"}]
    assert "phase" not in captured[0]["evidence"][0]
