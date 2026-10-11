from typing import Literal

import pytest

from matchlens.agents.triggers import RuleTriggerEngine, merge_candidates
from matchlens.models.clock import MatchClock
from matchlens.models.events import (
    CardAttrs,
    CardEvent,
    GoalAttrs,
    GoalEvent,
    PossessionChangeEvent,
    ShotAttrs,
    ShotEvent,
    ShotOutcome,
    format_event_id,
)
from matchlens.models.insights import Moment, MomentType
from matchlens.models.metrics import MetricSnapshot
from matchlens.models.pitch import Point

MATCH_ID = "trigger-test"


def clock(ms: int) -> MatchClock:
    return MatchClock(period=1, ms=ms)


def metric(
    metric_id: str,
    value: float,
    ms: int,
    *,
    scope: Literal["match", "team", "player", "event"] = "match",
    subject_id: str | None = None,
    seq: int = 1,
) -> MetricSnapshot:
    return MetricSnapshot(
        metric_id=metric_id,
        scope=scope,
        subject_id=subject_id,
        label=metric_id,
        value=value,
        unit="index" if scope == "match" else "",
        window="match",
        as_of_seq=seq,
        clock=clock(ms),
    )


def tick(seq: int, ms: int) -> PossessionChangeEvent:
    return PossessionChangeEvent(
        event_id=format_event_id(MATCH_ID, seq),
        match_id=MATCH_ID,
        seq=seq,
        clock=clock(ms),
        team_id="home",
    )


def shot(seq: int, ms: int, outcome: ShotOutcome = "saved") -> ShotEvent:
    return ShotEvent(
        event_id=format_event_id(MATCH_ID, seq),
        match_id=MATCH_ID,
        seq=seq,
        clock=clock(ms),
        team_id="home",
        player_id="h09",
        location=Point(x=90, y=34),
        outcome=outcome,
        attrs=ShotAttrs(
            body_part="foot",
            shot_speed_kmh=90,
            situation="open_play",
            assist_event_id=None,
        ),
    )


def goal(seq: int, ms: int) -> GoalEvent:
    return GoalEvent(
        event_id=format_event_id(MATCH_ID, seq),
        match_id=MATCH_ID,
        seq=seq,
        clock=clock(ms),
        team_id="home",
        player_id="h09",
        attrs=GoalAttrs(
            scorer_id="h09", assist_id=None, shot_event_id=format_event_id(MATCH_ID, seq - 1)
        ),
    )


def moment(seq: int, ms: int, subject: str, kind: MomentType = "milestone") -> Moment:
    return Moment(
        moment_id=f"{MATCH_ID}-{seq}-{kind}-{subject}",
        match_id=MATCH_ID,
        type=kind,
        seq_start=seq,
        seq_end=seq,
        clock=clock(ms),
        rule_score=0.3,
        significance=0.3,
        evidence_metric_ids=["player.h09.passes"],
        subject_ids=[subject],
        source="rule",
    )


def test_events_emit_goal_card_big_chance_and_first_shot_milestone() -> None:
    engine = RuleTriggerEngine(MATCH_ID)
    goal_moments = engine.consume(goal(2, 10_000), [])
    card = CardEvent(
        event_id=format_event_id(MATCH_ID, 3),
        match_id=MATCH_ID,
        seq=3,
        clock=clock(20_000),
        team_id="away",
        player_id="a04",
        outcome="yellow",
        attrs=CardAttrs(reason="late challenge"),
    )
    card_moments = engine.consume(card, [])
    big_shot = shot(4, 30_000, "blocked")
    chance = engine.consume(
        big_shot,
        [
            metric(
                "event.trigger-test-000004.xg",
                0.25,
                30_000,
                scope="event",
                subject_id="trigger-test-000004",
                seq=4,
            )
        ],
    )
    first_on_target = engine.consume(shot(5, 40_000), [])
    later_on_target = engine.consume(shot(6, 50_000), [])

    assert [(item.type, item.rule_score) for item in goal_moments] == [("goal", 1.0)]
    assert [(item.type, item.rule_score) for item in card_moments] == [("card", 0.4)]
    assert [item.type for item in chance] == ["big_chance"]
    assert [item.type for item in first_on_target] == ["milestone"]
    assert later_on_target == []


def test_momentum_press_control_and_speed_thresholds() -> None:
    engine = RuleTriggerEngine(MATCH_ID)
    assert engine.consume(tick(1, 1_000), [metric("match.momentum", 0, 1_000, seq=1)]) == []
    swing = engine.consume(tick(2, 4 * 60_000), [metric("match.momentum", 40, 4 * 60_000, seq=2)])
    assert [item.type for item in swing] == ["momentum_swing"]

    first_ppda = metric("team.home.ppda", 10, 0, scope="team", subject_id="home", seq=2)
    second_ppda = metric("team.home.ppda", 14, 10 * 60_000, scope="team", subject_id="home", seq=3)
    assert engine.consume(tick(3, 0), [first_ppda]) == []
    assert [item.type for item in engine.consume(tick(4, 10 * 60_000), [second_ppda])] == [
        "press_shift"
    ]

    assert (
        engine.consume(
            tick(5, 11 * 60_000), [metric("match.control_index", 26, 11 * 60_000, seq=5)]
        )
        == []
    )
    shift = engine.consume(
        tick(6, 12 * 60_000), [metric("match.control_index", -26, 12 * 60_000, seq=6)]
    )
    assert [item.type for item in shift] == ["control_shift"]

    low = metric(
        "player.h09.top_speed_kmh", 33.9, 13 * 60_000, scope="player", subject_id="h09", seq=7
    )
    high = metric(
        "player.h09.top_speed_kmh", 34, 14 * 60_000, scope="player", subject_id="h09", seq=8
    )
    assert engine.consume(tick(7, 13 * 60_000), [low]) == []
    assert [item.type for item in engine.consume(tick(8, 14 * 60_000), [high])] == ["speed_alert"]


def test_pass_milestone_and_periodic_spotlight() -> None:
    engine = RuleTriggerEngine(MATCH_ID)
    passes = metric("player.h09.passes", 49, 0, scope="player", subject_id="h09", seq=1)
    crossing = metric("player.h09.passes", 50, 1000, scope="player", subject_id="h09", seq=2)
    assert engine.consume(tick(1, 0), [passes]) == []
    assert [item.type for item in engine.consume(tick(2, 1000), [crossing])] == ["milestone"]

    spotlights = engine.consume(
        tick(3, 15 * 60_000),
        [metric("player.h09.xg", 0.7, 15 * 60_000, scope="player", subject_id="h09", seq=3)],
    )
    assert [item.type for item in spotlights] == ["player_spotlight"]
    assert spotlights[0].subject_ids == ["h09"]


def test_candidate_merging_requires_matching_type_subject_and_window() -> None:
    first = moment(1, 10_000, "h09")
    second = moment(2, 41_000, "h09")
    other_subject = moment(3, 20_000, "a09")
    different_type = moment(4, 20_000, "h09", "big_chance")
    critical = moment(5, 20_000, "h09", "goal")
    merged = merge_candidates([first, second, other_subject, different_type, critical])

    assert len(merged) == 5
    combined = merge_candidates([first, moment(6, 39_000, "h09")])
    assert len(combined) == 1
    assert combined[0].seq_start == 1
    assert combined[0].seq_end == 6
    assert combined[0].subject_ids == ["h09"]


def test_rejects_other_match() -> None:
    engine = RuleTriggerEngine(MATCH_ID)
    with pytest.raises(ValueError, match="match id mismatch"):
        engine.consume(goal(1, 0).model_copy(update={"match_id": "other-match"}), [])
