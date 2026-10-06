import asyncio
from pathlib import Path
from typing import Literal

import pytest

from matchlens.metrics.difficulty import pass_difficulty
from matchlens.metrics.engine import MetricsEngine
from matchlens.metrics.xg import expected_goals, shot_geometry
from matchlens.models.clock import MatchClock
from matchlens.models.events import (
    CardAttrs,
    CardEvent,
    DuelAttrs,
    GoalAttrs,
    GoalEvent,
    KickoffEvent,
    MatchEvent,
    NoAttrs,
    PassAttrs,
    PassEvent,
    PossessionChangeEvent,
    ShotAttrs,
    ShotEvent,
    TackleEvent,
    format_event_id,
)
from matchlens.models.metrics import MetricSnapshot
from matchlens.models.pitch import Point
from matchlens.models.tracking import PlayerPos, TrackingFrame
from matchlens.pipeline.replay import iter_inputs, replay_match
from matchlens.sim.match import SimulatedMatch, build_match_metadata
from matchlens.sim.output import write_match
from matchlens.store.memory import MemoryMetricStore
from matchlens.transport.local import LocalTransport
from matchlens.world.meridian import ASHMOOR_ROVERS, KESTREL_BAY, MERIDIAN_LEAGUE

MATCH_ID = "metric-test"


def clock(ms: int, period: Literal[1, 2] = 1) -> MatchClock:
    return MatchClock(period=period, ms=ms)


def pass_event(
    seq: int,
    ms: int,
    *,
    side: str = "home",
    start: float = 50,
    end: float = 75,
    pressure: bool = False,
    length: float = 25,
    outcome: str = "complete",
) -> PassEvent:
    return PassEvent.model_validate(
        {
            "event_id": format_event_id(MATCH_ID, seq),
            "match_id": MATCH_ID,
            "seq": seq,
            "clock": clock(ms),
            "team_id": side,
            "player_id": "h09" if side == "home" else "a09",
            "location": Point(x=start, y=34),
            "end_location": Point(x=end, y=34),
            "outcome": outcome,
            "attrs": PassAttrs(
                receiver_id="h10" if side == "home" else "a10",
                length_m=length,
                height="ground",
                under_pressure=pressure,
                ball_speed_kmh=40,
            ),
        }
    )


def sequence() -> list[MatchEvent]:
    events: list[MatchEvent] = [
        KickoffEvent(
            event_id=format_event_id(MATCH_ID, 1),
            match_id=MATCH_ID,
            seq=1,
            clock=clock(0),
            team_id="home",
            player_id="h09",
            location=Point(x=52.5, y=34),
            attrs=NoAttrs(),
        ),
    ]
    events.extend(pass_event(seq, seq * 10_000) for seq in range(2, 7))
    events.append(
        ShotEvent(
            event_id=format_event_id(MATCH_ID, 7),
            match_id=MATCH_ID,
            seq=7,
            clock=clock(70_000),
            team_id="home",
            player_id="h09",
            location=Point(x=95, y=34),
            outcome="goal",
            attrs=ShotAttrs(
                body_part="foot",
                shot_speed_kmh=90,
                situation="open_play",
                assist_event_id=format_event_id(MATCH_ID, 6),
            ),
        )
    )
    events.append(
        GoalEvent(
            event_id=format_event_id(MATCH_ID, 8),
            match_id=MATCH_ID,
            seq=8,
            clock=clock(71_000),
            team_id="home",
            player_id="h09",
            attrs=GoalAttrs(
                scorer_id="h09", assist_id="h10", shot_event_id=format_event_id(MATCH_ID, 7)
            ),
        )
    )
    events.append(
        PossessionChangeEvent(
            event_id=format_event_id(MATCH_ID, 9),
            match_id=MATCH_ID,
            seq=9,
            clock=clock(80_000),
            team_id="away",
            attrs=NoAttrs(),
        )
    )
    events.append(pass_event(10, 90_000, side="away", start=85, end=75))
    events.append(
        TackleEvent(
            event_id=format_event_id(MATCH_ID, 11),
            match_id=MATCH_ID,
            seq=11,
            clock=clock(100_000),
            team_id="home",
            player_id="h03",
            location=Point(x=80, y=34),
            outcome="won",
            attrs=DuelAttrs(opponent_id="a09"),
        )
    )
    events.append(
        CardEvent(
            event_id=format_event_id(MATCH_ID, 12),
            match_id=MATCH_ID,
            seq=12,
            clock=clock(110_000),
            team_id="away",
            player_id="a03",
            outcome="yellow",
            attrs=CardAttrs(reason="late challenge"),
        )
    )
    return events


def test_event_metrics_on_hand_built_sequence() -> None:
    engine = MetricsEngine(MATCH_ID)
    emitted = engine.consume_all(sequence())
    latest = {(item.metric_id, item.window): item for item in emitted}

    assert latest["team.home.goals", "match"].value == 1
    assert latest["team.home.passes", "match"].value == 5
    assert latest["player.h09.pass_accuracy_pct", "match"].value == 100
    assert latest["team.home.field_tilt_pct", "last_10m"].value == 100
    assert latest["team.home.ppda", "last_10m"].value == 1
    assert latest["match.control_index", "last_5m"].value > 25
    assert latest["match.momentum", "match"].value > 0
    assert latest["team.home.possession_pct", "match"].value == pytest.approx(81.8182)
    assert latest["team.home.possession_pct", "last_5m"].value == pytest.approx(81.8182)
    assert latest[f"event.{MATCH_ID}-000002.ball_speed_kmh", "match"].value == 40
    assert latest[f"event.{MATCH_ID}-000007.shot_speed_kmh", "match"].value == 90
    assert latest["player.h09.avg_pass_difficulty", "match"].value > 0
    expected = expected_goals(
        shot_geometry(Point(x=95, y=34), attacking_right=True), "foot", "open_play"
    )
    assert latest[f"event.{MATCH_ID}-000007.xg", "match"].value == pytest.approx(expected, abs=1e-4)
    assert latest["team.home.xg", "match"].value == pytest.approx(expected, abs=1e-4)
    assert latest["player.h09.xg", "match"].value == pytest.approx(expected, abs=1e-4)


def test_physical_metrics_from_frames() -> None:
    engine = MetricsEngine(MATCH_ID)

    def player(x: float, speed: float) -> PlayerPos:
        return PlayerPos(player_id="h09", x=x, y=34, speed_kmh=speed)

    frames = [
        TrackingFrame(
            match_id=MATCH_ID,
            frame_seq=1,
            clock=clock(0),
            ball=Point(x=50, y=34),
            ball_speed_kmh=0,
            players=[player(50, 0)],
        ),
        TrackingFrame(
            match_id=MATCH_ID,
            frame_seq=2,
            clock=clock(1000),
            ball=Point(x=50, y=34),
            ball_speed_kmh=0,
            players=[player(55, 26)],
        ),
        TrackingFrame(
            match_id=MATCH_ID,
            frame_seq=3,
            clock=clock(2000),
            ball=Point(x=50, y=34),
            ball_speed_kmh=0,
            players=[player(60, 27)],
        ),
    ]
    latest = {item.metric_id: item for item in engine.consume_all(frames)}
    assert latest["player.h09.distance_m"].value == 10
    assert latest["player.h09.top_speed_kmh"].value == 27
    assert latest["player.h09.sprints"].value == 1


def test_rolling_windows_expire_on_match_time() -> None:
    engine = MetricsEngine(MATCH_ID)
    engine.consume_all(sequence())
    later = TrackingFrame(
        match_id=MATCH_ID,
        frame_seq=1,
        clock=clock(12 * 60_000),
        ball=Point(x=50, y=34),
        ball_speed_kmh=0,
        players=[],
    )
    latest = {item.metric_id: item for item in engine.consume_frame(later)}
    assert latest["team.home.ppda"].value == 0
    assert latest["team.home.field_tilt_pct"].value == 0
    assert latest["match.control_index"].value == 0
    assert latest["team.home.possession_pct"].value == 100


def test_second_period_accepts_first_half_stoppage_time() -> None:
    engine = MetricsEngine(MATCH_ID)
    first = KickoffEvent(
        event_id=format_event_id(MATCH_ID, 1),
        match_id=MATCH_ID,
        seq=1,
        clock=clock(46 * 60_000),
        team_id="home",
        player_id="h09",
        location=Point(x=52.5, y=34),
        attrs=NoAttrs(),
    )
    second = KickoffEvent(
        event_id=format_event_id(MATCH_ID, 2),
        match_id=MATCH_ID,
        seq=2,
        clock=clock(0, period=2),
        team_id="away",
        player_id="a09",
        location=Point(x=52.5, y=34),
        attrs=NoAttrs(),
    )
    engine.consume_event(first)
    engine.consume_event(second)
    assert engine.clock.period == 2


def test_pass_difficulty_and_xg_are_monotonic() -> None:
    easy = pass_event(2, 20_000, length=10, end=60)
    hard = pass_event(2, 20_000, length=35, end=85, pressure=True)
    assert pass_difficulty(hard) > pass_difficulty(easy)
    central = expected_goals(
        shot_geometry(Point(x=95, y=34), attacking_right=True), "foot", "open_play"
    )
    distant = expected_goals(
        shot_geometry(Point(x=75, y=34), attacking_right=True), "foot", "open_play"
    )
    wide = expected_goals(
        shot_geometry(Point(x=95, y=10), attacking_right=True), "foot", "open_play"
    )
    assert central > distant
    assert central > wide


def test_store_historical_lookup() -> None:
    async def exercise() -> None:
        store = MemoryMetricStore()
        engine = MetricsEngine(MATCH_ID)
        for event in sequence():
            for snapshot in engine.consume_event(event):
                await store.put(MATCH_ID, snapshot)
        assert await store.get(MATCH_ID, "team.home.goals", 7) is None
        assert (await store.get(MATCH_ID, "team.home.goals", 8)).value == 1  # type: ignore[union-attr]
        assert (await store.get(MATCH_ID, "team.home.passes", 4)).value == 3  # type: ignore[union-attr]
        rolling = await store.get(MATCH_ID, "team.home.possession_pct", 12, "last_5m")
        assert rolling is not None
        assert rolling.window == "last_5m"
        assert await store.get("other", "team.home.goals") is None

    asyncio.run(exercise())


def test_stream_and_batch_parity(tmp_path: Path) -> None:
    metadata = build_match_metadata(
        MERIDIAN_LEAGUE, KESTREL_BAY, ASHMOOR_ROVERS, scenario="balanced", seed=1
    )
    metadata = metadata.model_copy(update={"match_id": MATCH_ID})
    frames = [
        TrackingFrame(
            match_id=MATCH_ID,
            frame_seq=index,
            clock=clock(index * 1000),
            ball=Point(x=50, y=34),
            ball_speed_kmh=0,
            players=[PlayerPos(player_id="h09", x=50 + index, y=34, speed_kmh=3.6)],
        )
        for index in range(1, 3)
    ]
    match_dir = write_match(SimulatedMatch(metadata, sequence(), frames), tmp_path)
    batch = MetricsEngine(MATCH_ID).consume_all(iter_inputs(match_dir))

    async def streamed() -> list[MetricSnapshot]:
        return await replay_match(match_dir, LocalTransport(maxsize=2), MemoryMetricStore())

    assert asyncio.run(streamed()) == batch
