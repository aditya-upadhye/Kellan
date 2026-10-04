import math
from collections import defaultdict
from pathlib import Path

import pytest

from matchlens.models.clock import MatchClock
from matchlens.models.events import (
    CardEvent,
    CarryAttrs,
    CarryEvent,
    KickoffEvent,
    MatchEvent,
    SubstitutionEvent,
    format_event_id,
)
from matchlens.models.pitch import Point
from matchlens.models.tracking import TrackingFrame
from matchlens.sim.match import SimulatedMatch, build_match_metadata, simulate_match
from matchlens.sim.output import FRAMES_FILE, write_match
from matchlens.sim.space import Spot
from matchlens.sim.tracking import FRAME_INTERVAL_MS, MAX_REPORTED_SPEED_KMH, BallTrack
from matchlens.world.meridian import MERIDIAN_LEAGUE


def located_event(seq: int, ms: int, location: Spot, end: Spot | None = None) -> MatchEvent:
    clock = MatchClock(period=1, ms=ms)
    event_id = format_event_id("m1", seq)
    if end is None:
        return KickoffEvent(
            event_id=event_id,
            match_id="m1",
            seq=seq,
            clock=clock,
            team_id="home",
            player_id="h09",
            location=Point(x=location.x, y=location.y),
        )
    return CarryEvent(
        event_id=event_id,
        match_id="m1",
        seq=seq,
        clock=clock,
        team_id="home",
        player_id="h09",
        location=Point(x=location.x, y=location.y),
        end_location=Point(x=end.x, y=end.y),
        attrs=CarryAttrs(distance_m=location.distance_to(end)),
    )


def test_ball_rests_on_event_locations_and_moves_between_them() -> None:
    track = BallTrack.from_events(
        [located_event(1, 0, Spot(52.5, 34.0)), located_event(2, 4_000, Spot(60.5, 34.0))]
    )

    assert track.position(1, 0) == Spot(52.5, 34.0)
    assert track.position(1, 2_000) == Spot(56.5, 34.0)
    assert track.position(1, 9_000) == Spot(60.5, 34.0)
    assert track.position(2, 0) == Spot(52.5, 34.0)


def test_ball_reaches_the_end_of_a_carry_at_carrying_speed() -> None:
    track = BallTrack.from_events(
        [
            located_event(1, 0, Spot(40.0, 34.0), end=Spot(50.0, 34.0)),
            located_event(2, 10_000, Spot(50.0, 34.0)),
        ]
    )

    assert track.position(1, 2_000) == Spot(50.0, 34.0)
    assert track.position(1, 6_000) == Spot(50.0, 34.0)


@pytest.fixture(scope="module")
def tracked_match() -> SimulatedMatch:
    metadata = build_match_metadata(
        MERIDIAN_LEAGUE,
        MERIDIAN_LEAGUE.club("kestrel-bay"),
        MERIDIAN_LEAGUE.club("ashmoor-rovers"),
        scenario="tracking",
        seed=7,
    )
    return simulate_match(metadata)


def frames_of_period(match: SimulatedMatch, period: int) -> list[TrackingFrame]:
    return [frame for frame in match.frames if frame.clock.period == period]


def test_frames_tick_at_one_hertz_through_each_period(tracked_match: SimulatedMatch) -> None:
    assert [frame.frame_seq for frame in tracked_match.frames] == list(
        range(1, len(tracked_match.frames) + 1)
    )
    for period in (1, 2):
        frames = frames_of_period(tracked_match, period)
        period_end_ms = max(
            event.clock.ms for event in tracked_match.events if event.clock.period == period
        )

        assert [frame.clock.ms for frame in frames] == list(
            range(0, frames[-1].clock.ms + 1, FRAME_INTERVAL_MS)
        )
        assert period_end_ms - FRAME_INTERVAL_MS < frames[-1].clock.ms <= period_end_ms


def test_frames_track_exactly_the_players_on_the_pitch(tracked_match: SimulatedMatch) -> None:
    on_pitch = {
        player.player_id
        for team in (tracked_match.metadata.home, tracked_match.metadata.away)
        for player in team.players
        if player.starter
    }
    events = iter(tracked_match.events)
    pending = next(events, None)
    for frame in tracked_match.frames:
        while pending is not None and (pending.clock.period, pending.clock.ms) <= (
            frame.clock.period,
            frame.clock.ms,
        ):
            if isinstance(pending, SubstitutionEvent):
                on_pitch.remove(pending.attrs.player_out_id)
                on_pitch.add(pending.attrs.player_in_id)
            elif isinstance(pending, CardEvent) and pending.outcome in ("red", "second_yellow"):
                on_pitch.remove(pending.player_id)
            pending = next(events, None)

        assert {player.player_id for player in frame.players} == on_pitch, frame.frame_seq


def test_reported_speed_matches_movement_between_frames(tracked_match: SimulatedMatch) -> None:
    previous: dict[str, tuple[float, float]] = {}
    for frame in tracked_match.frames:
        current = {player.player_id: (player.x, player.y) for player in frame.players}
        for player in frame.players:
            assert player.speed_kmh <= MAX_REPORTED_SPEED_KMH
            if frame.clock.ms == 0 or player.player_id not in previous:
                continue
            moved_kmh = math.dist(previous[player.player_id], current[player.player_id]) * 3.6
            assert player.speed_kmh == pytest.approx(
                min(moved_kmh, MAX_REPORTED_SPEED_KMH), abs=0.06
            )
        previous = current


def test_movement_looks_like_football(tracked_match: SimulatedMatch) -> None:
    roles = {
        player.player_id: player.role
        for team in (tracked_match.metadata.home, tracked_match.metadata.away)
        for player in team.players
    }
    distance_m: dict[str, float] = defaultdict(float)
    seconds_played: dict[str, int] = defaultdict(int)
    top_speed: dict[str, float] = defaultdict(float)
    for frame in tracked_match.frames:
        for player in frame.players:
            distance_m[player.player_id] += player.speed_kmh / 3.6
            seconds_played[player.player_id] += 1
            top_speed[player.player_id] = max(top_speed[player.player_id], player.speed_kmh)
    full_match_outfield = [
        player_id
        for player_id, seconds in seconds_played.items()
        if seconds > 90 * 60 and roles[player_id] != "GK"
    ]

    assert full_match_outfield
    assert all(7_000 <= distance_m[player_id] <= 13_000 for player_id in full_match_outfield)
    assert all(27.0 <= top_speed[player_id] <= 36.0 for player_id in full_match_outfield)
    assert max(frame.ball_speed_kmh for frame in tracked_match.frames) < 140.0


def test_writes_frames_alongside_events(tracked_match: SimulatedMatch, tmp_path: Path) -> None:
    match_dir = write_match(tracked_match, tmp_path)

    lines = (match_dir / FRAMES_FILE).read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(tracked_match.frames)
    assert TrackingFrame.model_validate_json(lines[-1]) == tracked_match.frames[-1]
