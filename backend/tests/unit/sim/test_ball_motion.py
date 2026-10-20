import pytest

from matchlens.models.clock import MatchClock
from matchlens.models.events import (
    KickoffEvent,
    PassAttrs,
    PassEvent,
    PassHeight,
    ShotAttrs,
    ShotEvent,
)
from matchlens.models.pitch import Point
from matchlens.sim.space import Spot
from matchlens.sim.tracking import BallTrack


def pass_event(height: PassHeight, *, start_ms: int = 0, length: float = 20.0) -> PassEvent:
    return PassEvent(
        event_id="m1-000001",
        match_id="m1",
        seq=1,
        clock=MatchClock(period=1, ms=start_ms),
        team_id="home",
        player_id="h06",
        location=Point(x=40, y=34),
        end_location=Point(x=40 + length, y=34),
        outcome="complete",
        attrs=PassAttrs(
            receiver_id="h09",
            length_m=length,
            height=height,
            under_pressure=False,
            ball_speed_kmh=72,
        ),
    )


def test_loft_is_authored_only_for_aerial_passes() -> None:
    ground = BallTrack.from_events([pass_event("ground")])
    high = BallTrack.from_events([pass_event("high")])
    assert all(sample.height_m == 0 for sample in ground.trajectory(1, 1000))
    assert max(sample.height_m for sample in high.trajectory(1, 1000)) > 2
    # Arrival is a contact at ground height, with the event endpoint preserved.
    arrival = high.flight_at(1, 0)
    assert arrival is not None
    assert high.position(1, arrival.arrival_ms) == Spot(60, 34)
    assert high.trajectory(1, 2000)[-1].height_m == 0


def test_subsecond_pass_keeps_its_exact_departure_and_arrival() -> None:
    event = pass_event("ground", start_ms=200, length=4)
    track = BallTrack.from_events([event])
    samples = track.trajectory(1, 1000)
    offsets = [sample.offset_ms for sample in samples]
    assert offsets == sorted(set(offsets))
    assert {0, 200, 500, 1000} <= set(offsets)
    takeoff = next(sample for sample in samples if sample.offset_ms == 200)
    landing = next(sample for sample in samples if sample.offset_ms == 500)
    assert (takeoff.x, takeoff.progress, takeoff.actor_id) == (40, 0, "h06")
    assert (landing.x, landing.progress) == (44, 1)
    assert landing.event_id == event.event_id


def test_goal_waits_for_restart_instead_of_drifting_across_the_pitch() -> None:
    shot = ShotEvent(
        event_id="m1-000001",
        match_id="m1",
        seq=1,
        clock=MatchClock(period=1, ms=0),
        team_id="home",
        player_id="h09",
        location=Point(x=95, y=34),
        end_location=Point(x=105, y=35),
        outcome="goal",
        attrs=ShotAttrs(
            body_part="foot", shot_speed_kmh=90, situation="open_play", assist_event_id=None
        ),
    )
    restart = KickoffEvent(
        event_id="m1-000002",
        match_id="m1",
        seq=2,
        clock=MatchClock(period=1, ms=60000),
        team_id="away",
        player_id="a09",
        location=Point(x=52.5, y=34),
    )
    track = BallTrack.from_events([shot, restart])
    assert track.position(1, 30000) == Spot(105, 35)
    assert track.position(1, 59999) == Spot(105, 35)
    assert track.position(1, 60000) == Spot(52.5, 34)
    assert not track.restarted(1, 58000, 59000)
    assert track.restarted(1, 59000, 60000)
    samples = track.trajectory(1, 60000)
    assert samples[-2].offset_ms == 999
    assert samples[-2].x == 105
    assert samples[-1].x == 52.5


def test_trajectory_stays_within_its_second_and_finishes_at_the_tracking_position() -> None:
    track = BallTrack.from_events([pass_event("low")])
    for ms in (1000, 2000, 3000):
        samples = track.trajectory(1, ms)
        assert samples[0].offset_ms == 0
        assert samples[-1].offset_ms == 1000
        assert samples[-1].x == pytest.approx(track.position(1, ms).x, abs=0.001)
        assert all(0 <= sample.height_m <= 12 for sample in samples)
