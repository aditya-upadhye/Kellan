import asyncio
from collections.abc import Callable
from contextlib import aclosing
from dataclasses import replace
from functools import partial
from threading import Event
from time import monotonic

import pytest

from matchlens.config import get_settings
from matchlens.models.clock import MatchClock
from matchlens.models.match import MatchMetadata
from matchlens.models.pitch import Point
from matchlens.models.tracking import TrackingFrame
from matchlens.sim import engine as engine_module
from matchlens.sim import stream
from matchlens.sim.match import build_scenario_metadata, simulate_match
from matchlens.sim.scenarios import load_scenario
from matchlens.sim.tuning import DEFAULT_TUNING
from matchlens.world.meridian import MERIDIAN_LEAGUE


@pytest.fixture
def metadata() -> MatchMetadata:
    scenario = load_scenario("balanced", get_settings().scenarios_dir)
    return build_scenario_metadata(MERIDIAN_LEAGUE, scenario, 42)


def frame(metadata: MatchMetadata, seq: int) -> TrackingFrame:
    return TrackingFrame(
        match_id=metadata.match_id,
        frame_seq=seq,
        clock=MatchClock(period=1, ms=seq * 1000),
        ball=Point(x=52.5, y=34),
        ball_speed_kmh=0,
        players=[],
    )


def test_publisher_keeps_only_the_latest_frame_at_an_instant(metadata: MatchMetadata) -> None:
    received: list[stream.MatchInput] = []
    publisher = stream.OrderedPublisher(received.append)
    first = frame(metadata, 1)
    updated = first.model_copy(update={"ball_speed_kmh": 5.0})
    publisher.push(first)
    publisher.push(updated)
    assert not received
    publisher.push(frame(metadata, 2))
    assert received == [updated]
    publisher.flush()
    assert len(received) == 2
    with pytest.raises(ValueError, match="backwards"):
        publisher.push(first)


def test_live_kickoff_arrives_within_five_seconds(metadata: MatchMetadata) -> None:
    async def exercise() -> None:
        start = monotonic()
        async with aclosing(stream.stream_match(metadata)) as inputs:
            first = await asyncio.wait_for(anext(inputs), timeout=5)
            assert first.clock.ms == 0
            assert monotonic() - start < 5
            received = [first]
            for _ in range(10):
                received.append(await asyncio.wait_for(anext(inputs), timeout=5))
            stamps = [(item.clock.period, item.clock.ms) for item in received]
            assert stamps == sorted(stamps)
            assert any(isinstance(item, TrackingFrame) for item in received)

    asyncio.run(exercise())


def test_backpressure_and_closing_stop_generation(
    metadata: MatchMetadata, monkeypatch: pytest.MonkeyPatch
) -> None:
    finished = Event()
    produced: list[int] = []

    class FastEngine:
        def __init__(
            self, *args: object, on_input: Callable[[stream.MatchInput], None], **kwargs: object
        ) -> None:
            self.publish = on_input

        def run(self) -> None:
            try:
                for seq in range(1, 1001):
                    produced.append(seq)
                    self.publish(frame(metadata, seq))
            finally:
                finished.set()

    monkeypatch.setattr(stream, "MatchEngine", FastEngine)

    async def exercise() -> None:
        async with aclosing(stream.stream_match(metadata)) as inputs:
            await asyncio.wait_for(anext(inputs), timeout=5)
            await asyncio.sleep(0.1)
            assert len(produced) <= stream.BUFFER_ITEMS + 3
            assert not finished.is_set()
        assert finished.is_set()

    asyncio.run(exercise())


def test_worker_errors_reach_the_consumer(
    metadata: MatchMetadata, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailedEngine:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def run(self) -> None:
            raise ValueError("generation failed")

    monkeypatch.setattr(stream, "MatchEngine", FailedEngine)

    async def exercise() -> None:
        async with aclosing(stream.stream_match(metadata)) as inputs:
            with pytest.raises(ValueError, match="generation failed"):
                await asyncio.wait_for(anext(inputs), timeout=5)

    asyncio.run(exercise())


def test_progressive_output_matches_offline_simulation(
    metadata: MatchMetadata, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine_module, "REGULATION_PERIOD_MS", 10_000)
    tuning = replace(DEFAULT_TUNING, added_time_ms=(0, 0))
    offline = simulate_match(metadata, tuning)
    expected = sorted(
        [*offline.events, *offline.frames],
        key=lambda item: (item.clock.period, item.clock.ms, isinstance(item, TrackingFrame)),
    )
    monkeypatch.setattr(stream, "MatchEngine", partial(engine_module.MatchEngine, tuning=tuning))

    async def exercise() -> None:
        actual = [item async for item in stream.stream_match(metadata)]
        assert actual == expected

    asyncio.run(exercise())
