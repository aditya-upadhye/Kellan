import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from matchlens.metrics.engine import MetricsEngine
from matchlens.models.envelope import StreamEnvelope
from matchlens.models.events import MATCH_EVENT_ADAPTER, MatchEvent
from matchlens.models.match import MatchMetadata
from matchlens.models.metrics import MetricSnapshot
from matchlens.models.tracking import TrackingFrame
from matchlens.sim.output import EVENTS_FILE, FRAMES_FILE, METADATA_FILE
from matchlens.store.base import MetricStore
from matchlens.transport.base import MatchTransport

ReplaySpeed = Literal[1, 10, 30, 60, "max"]


def read_match(match_dir: Path) -> tuple[MatchMetadata, Iterator[MatchEvent | TrackingFrame]]:
    metadata = MatchMetadata.model_validate_json(
        (match_dir / METADATA_FILE).read_text(encoding="utf-8")
    )
    return metadata, iter_inputs(match_dir)


def iter_inputs(match_dir: Path) -> Iterator[MatchEvent | TrackingFrame]:
    """Merge already ordered event and frame files; events precede frames at equal time."""
    with (match_dir / EVENTS_FILE).open(encoding="utf-8") as event_file:
        frames_path = match_dir / FRAMES_FILE
        if not frames_path.exists():
            for line in event_file:
                yield MATCH_EVENT_ADAPTER.validate_json(line)
            return
        with frames_path.open(encoding="utf-8") as frame_file:
            events = (MATCH_EVENT_ADAPTER.validate_json(line) for line in event_file)
            frames = (TrackingFrame.model_validate_json(line) for line in frame_file)
            event = next(events, None)
            frame = next(frames, None)
            while event is not None or frame is not None:
                if event is not None and (
                    frame is None
                    or (event.clock.period, event.clock.ms) <= (frame.clock.period, frame.clock.ms)
                ):
                    yield event
                    event = next(events, None)
                elif frame is not None:
                    yield frame
                    frame = next(frames, None)


def to_envelope(item: MatchEvent | TrackingFrame) -> StreamEnvelope:
    return StreamEnvelope(
        kind="frame" if isinstance(item, TrackingFrame) else "event",
        match_id=item.match_id,
        data=item.model_dump(mode="json"),
    )


async def consume_message(
    engine: MetricsEngine, store: MetricStore, message: StreamEnvelope
) -> list[MetricSnapshot]:
    if message.kind == "event":
        snapshots = engine.consume_event(MATCH_EVENT_ADAPTER.validate_python(message.data))
    elif message.kind == "frame":
        snapshots = engine.consume_frame(TrackingFrame.model_validate(message.data))
    else:
        return []
    for snapshot in snapshots:
        await store.put(message.match_id, snapshot)
    return snapshots


async def replay_match(
    match_dir: Path, transport: MatchTransport, store: MetricStore, speed: ReplaySpeed = "max"
) -> list[MetricSnapshot]:
    metadata, inputs = read_match(match_dir)
    engine = MetricsEngine(metadata.match_id)
    output: list[MetricSnapshot] = []

    async def publish() -> None:
        previous: tuple[int, int] | None = None
        for item in inputs:
            stamp = (item.clock.period, item.clock.ms)
            if speed != "max" and previous is not None:
                delta = (stamp[0] - previous[0]) * 45 * 60_000 + stamp[1] - previous[1]
                if delta > 0:
                    await asyncio.sleep(delta / (1000 * speed))
            await transport.publish(to_envelope(item))
            previous = stamp
        await transport.publish(
            StreamEnvelope(kind="status", match_id=metadata.match_id, data={"state": "complete"})
        )

    async def consume() -> None:
        async for message in transport.subscribe():
            if message.match_id != metadata.match_id:
                continue
            if message.kind == "status" and message.data.get("state") == "complete":
                break
            output.extend(await consume_message(engine, store, message))

    producer = asyncio.create_task(publish())
    consumer = asyncio.create_task(consume())
    try:
        done, _ = await asyncio.wait({producer, consumer}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        await producer
        await consumer
    finally:
        producer.cancel()
        consumer.cancel()
        await transport.close()
    return output
