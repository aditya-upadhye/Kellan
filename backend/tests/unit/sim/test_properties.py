from itertools import pairwise
from typing import TYPE_CHECKING

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from matchlens.config import get_settings
from matchlens.models.events import (
    CarryEvent,
    DuelEvent,
    KickoffEvent,
    PassEvent,
    PossessionChangeEvent,
    ShotEvent,
)
from matchlens.models.pitch import PITCH_LENGTH_M, PITCH_WIDTH_M, Point
from matchlens.sim import engine as engine_module
from matchlens.sim.match import simulate_scenario
from matchlens.sim.scenarios import load_scenario, scenario_names
from matchlens.sim.tracking import MAX_REPORTED_SPEED_KMH
from matchlens.world.meridian import MERIDIAN_LEAGUE
from support.match_stats import possession_shares

if TYPE_CHECKING:
    from matchlens.models.base import TeamSide

SCENARIOS_DIR = get_settings().scenarios_dir
seeds = st.integers(min_value=0, max_value=2**31 - 1)
scenarios = st.sampled_from(scenario_names(SCENARIOS_DIR))


@pytest.fixture(autouse=True)
def bounded_property_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    # These properties concern local stream coherence and coordinate/speed
    # bounds, including the period transition. Keep all generated examples;
    # full-match totals, substitutions and workload have dedicated tests, and
    # the 50-seed realism sweep still plays complete regulation matches.
    monkeypatch.setattr(engine_module, "REGULATION_PERIOD_MS", 60_000)


def on_pitch(point: Point) -> bool:
    return 0.0 <= point.x <= PITCH_LENGTH_M and 0.0 <= point.y <= PITCH_WIDTH_M


@settings(max_examples=12)
@given(name=scenarios, seed=seeds)
def test_any_seed_keeps_the_event_stream_coherent(name: str, seed: int) -> None:
    match = simulate_scenario(
        MERIDIAN_LEAGUE, load_scenario(name, SCENARIOS_DIR), seed, with_tracking=False
    )
    events = match.events

    assert all(later.seq == earlier.seq + 1 for earlier, later in pairwise(events))
    assert all(
        (earlier.clock.period, earlier.clock.ms) <= (later.clock.period, later.clock.ms)
        for earlier, later in pairwise(events)
    )
    for event in events:
        for point in (event.location, event.end_location):
            assert point is None or on_pitch(point)

    shares = possession_shares(events)
    assert sum(shares.values()) == pytest.approx(100.0)
    assert all(0.0 <= share <= 100.0 for share in shares.values())

    holder: TeamSide | None = None
    for event in events:
        if isinstance(event, KickoffEvent | PossessionChangeEvent):
            holder = event.team_id
        elif isinstance(event, PassEvent | CarryEvent | ShotEvent | DuelEvent):
            assert event.team_id == holder


@pytest.mark.slow
@settings(max_examples=3)
@given(seed=seeds)
def test_any_tracking_stream_stays_on_the_pitch_and_under_the_speed_cap(seed: int) -> None:
    match = simulate_scenario(MERIDIAN_LEAGUE, load_scenario("balanced", SCENARIOS_DIR), seed)

    for frame in match.frames:
        assert on_pitch(frame.ball)
        for player in frame.players:
            assert on_pitch(Point(x=player.x, y=player.y))
            assert 0.0 <= player.speed_kmh <= MAX_REPORTED_SPEED_KMH
