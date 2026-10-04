from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from matchlens.models.clock import MS_PER_MINUTE
from matchlens.models.events import (
    MATCH_EVENT_ADAPTER,
    CardEvent,
    CarryEvent,
    DuelEvent,
    GoalEvent,
    KickoffEvent,
    MatchEndEvent,
    MatchEvent,
    PassEvent,
    PeriodEndEvent,
    PossessionChangeEvent,
    ShotEvent,
    SubstitutionEvent,
)
from matchlens.sim.match import SimulatedMatch, build_match_metadata, simulate_match
from matchlens.sim.output import EVENTS_FILE, METADATA_FILE, write_match
from matchlens.world.meridian import MERIDIAN_LEAGUE

if TYPE_CHECKING:
    from matchlens.models.base import TeamSide

FIXTURES = [
    ("kestrel-bay", "ashmoor-rovers", 1),
    ("kestrel-bay", "ashmoor-rovers", 2),
    ("port-halden", "vellmont-city", 3),
]


@pytest.fixture(scope="module", params=FIXTURES, ids=lambda fixture: f"{fixture[0]}-s{fixture[2]}")
def match(request: pytest.FixtureRequest) -> SimulatedMatch:
    home_id, away_id, seed = request.param
    metadata = build_match_metadata(
        MERIDIAN_LEAGUE,
        MERIDIAN_LEAGUE.club(home_id),
        MERIDIAN_LEAGUE.club(away_id),
        scenario="invariants",
        seed=seed,
    )
    return simulate_match(metadata, with_tracking=False)


def test_sequence_numbers_count_up_from_one(match: SimulatedMatch) -> None:
    assert [event.seq for event in match.events] == list(range(1, len(match.events) + 1))


def test_clock_never_runs_backwards(match: SimulatedMatch) -> None:
    timeline = [(event.clock.period, event.clock.ms) for event in match.events]

    assert timeline == sorted(timeline)


def test_periods_start_with_kickoff_and_end_after_added_time(match: SimulatedMatch) -> None:
    for period, closing_type in ((1, PeriodEndEvent), (2, MatchEndEvent)):
        period_events = [event for event in match.events if event.clock.period == period]

        assert isinstance(period_events[0], KickoffEvent)
        assert isinstance(period_events[-1], closing_type)
        assert 46 * MS_PER_MINUTE <= period_events[-1].clock.ms <= 51 * MS_PER_MINUTE
    assert isinstance(match.events[-1], MatchEndEvent)


def test_every_event_round_trips_through_json(match: SimulatedMatch) -> None:
    for event in match.events:
        assert MATCH_EVENT_ADAPTER.validate_json(event.model_dump_json()) == event


def test_only_the_team_in_possession_plays_the_ball(match: SimulatedMatch) -> None:
    possession: TeamSide | None = None
    for event in match.events:
        if isinstance(event, KickoffEvent | PossessionChangeEvent):
            possession = event.team_id
        elif isinstance(event, PassEvent | CarryEvent | ShotEvent | DuelEvent):
            assert event.team_id == possession, event.event_id


def test_goals_follow_their_shot_and_the_other_team_restarts(match: SimulatedMatch) -> None:
    events = match.events
    goals = [index for index, event in enumerate(events) if isinstance(event, GoalEvent)]
    scoring_shots = [e for e in events if isinstance(e, ShotEvent) and e.outcome == "goal"]

    assert len(goals) == len(scoring_shots)
    for index in goals:
        goal = events[index]
        shot = events[index - 1]
        assert isinstance(goal, GoalEvent)
        assert isinstance(shot, ShotEvent)
        assert goal.attrs.shot_event_id == shot.event_id
        assert goal.player_id == shot.player_id
        restart = next(event for event in events[index:] if isinstance(event, KickoffEvent))
        assert restart.team_id != goal.team_id


def test_assists_point_to_a_completed_pass_to_the_shooter(match: SimulatedMatch) -> None:
    passes = {event.event_id: event for event in match.events if isinstance(event, PassEvent)}
    for shot in (event for event in match.events if isinstance(event, ShotEvent)):
        if shot.attrs.assist_event_id is None:
            continue
        assist = passes[shot.attrs.assist_event_id]
        assert assist.outcome == "complete"
        assert assist.team_id == shot.team_id
        assert assist.attrs.receiver_id == shot.player_id


def test_players_act_only_while_on_the_pitch(match: SimulatedMatch) -> None:
    on_pitch = {
        player.player_id
        for team in (match.metadata.home, match.metadata.away)
        for player in team.players
        if player.starter
    }
    for event in match.events:
        if isinstance(event, SubstitutionEvent):
            assert event.attrs.player_out_id in on_pitch
            assert event.attrs.player_in_id not in on_pitch
            on_pitch.remove(event.attrs.player_out_id)
            on_pitch.add(event.attrs.player_in_id)
            continue
        if event.player_id is not None:
            assert event.player_id in on_pitch, event.event_id
        if isinstance(event, PassEvent):
            assert event.attrs.receiver_id in on_pitch, event.event_id
        if isinstance(event, CardEvent) and event.outcome in ("red", "second_yellow"):
            on_pitch.remove(event.player_id)


def test_second_yellow_follows_a_first(match: SimulatedMatch) -> None:
    yellows: Counter[str] = Counter()
    for event in match.events:
        if isinstance(event, CardEvent):
            if event.outcome == "second_yellow":
                assert yellows[event.player_id] == 1
            yellows[event.player_id] += 1


def test_each_team_makes_three_to_five_second_half_substitutions(match: SimulatedMatch) -> None:
    substitutions = [event for event in match.events if isinstance(event, SubstitutionEvent)]
    per_team = Counter(event.team_id for event in substitutions)

    assert all(3 <= per_team[side] <= 5 for side in ("home", "away"))
    for event in substitutions:
        assert event.clock.period == 2
        assert 55 <= 45 + event.clock.ms / MS_PER_MINUTE <= 85


def test_shots_come_from_the_attacking_half(match: SimulatedMatch) -> None:
    for shot in (event for event in match.events if isinstance(event, ShotEvent)):
        attacking_right = (shot.team_id == "home") == (shot.clock.period == 1)
        distance_to_goal_line = 105.0 - shot.location.x if attacking_right else shot.location.x

        assert distance_to_goal_line < 52.5, shot.event_id


def event_types(events: list[MatchEvent]) -> set[str]:
    return {event.type.value for event in events}


def test_matches_produce_every_core_event_type(match: SimulatedMatch) -> None:
    assert {
        "kickoff",
        "pass",
        "carry",
        "shot",
        "tackle",
        "interception",
        "pressure",
        "duel",
        "foul",
        "substitution",
        "possession_change",
        "ball_out",
        "period_end",
        "match_end",
    } <= event_types(match.events)


def test_writes_metadata_and_events(match: SimulatedMatch, tmp_path: Path) -> None:
    match_dir = write_match(match, tmp_path)

    lines = (match_dir / EVENTS_FILE).read_bytes().split(b"\n")
    assert match_dir.name == match.metadata.match_id
    assert (match_dir / METADATA_FILE).read_text(encoding="utf-8").startswith("{")
    assert len(lines) == len(match.events) + 1
    assert b"\r" not in lines[0]
    assert MATCH_EVENT_ADAPTER.validate_json(lines[0]) == match.events[0]
