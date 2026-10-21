"""Bounded progressive match generation, independent of playback speed."""

import asyncio
from collections.abc import AsyncGenerator, Callable, Sequence
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import suppress
from random import Random
from threading import Event

from matchlens.models.events import BaseEvent
from matchlens.models.match import MatchMetadata
from matchlens.models.tracking import TrackingFrame
from matchlens.sim.engine import MatchEngine
from matchlens.sim.scenarios import Injection

MatchInput = BaseEvent | TrackingFrame
BUFFER_ITEMS = 64


class _StoppedError(Exception):
    pass


class OrderedPublisher:
    """Hold one clock instant so events precede frames at that instant."""

    def __init__(self, publish: Callable[[MatchInput], None]) -> None:
        self.publish = publish
        self.stamp = (0, 0)
        self.pending: dict[tuple[int, int], MatchInput] = {}

    def push(self, item: MatchInput) -> None:
        stamp = item.clock.period, item.clock.ms
        if stamp < self.stamp:
            raise ValueError("simulation input clock moved backwards")
        if stamp > self.stamp:
            self.flush()
            self.stamp = stamp
        key = (1, item.frame_seq) if isinstance(item, TrackingFrame) else (0, item.seq)
        # Restart placement can update the latest, not-yet-published frame.
        self.pending[key] = item

    def flush(self) -> None:
        for key in sorted(self.pending):
            self.publish(self.pending[key])
        self.pending.clear()


async def stream_match(
    metadata: MatchMetadata, *, script: Sequence[Injection] = ()
) -> AsyncGenerator[MatchInput]:
    """Yield as generation progresses; closing the iterator stops the worker.

    The bounded queue propagates playback/producer pauses into the simulation
    thread. The worker retains only the latest frame, not a second full match.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[MatchInput | Exception | None] = asyncio.Queue(BUFFER_ITEMS)
    stopped = Event()

    def send(item: MatchInput | Exception | None) -> None:
        if stopped.is_set():
            raise _StoppedError
        future = asyncio.run_coroutine_threadsafe(queue.put(item), loop)
        while True:
            try:
                future.result(timeout=0.05)
                return
            except FutureTimeout:
                if stopped.is_set():
                    future.cancel()
                    raise _StoppedError from None

    def generate() -> None:
        publisher = OrderedPublisher(send)
        try:
            engine = MatchEngine(
                metadata,
                Random(metadata.seed),
                script=script,
                on_input=publisher.push,
                retain_history=False,
            )
            engine.run()
            publisher.flush()
            send(None)
        except _StoppedError:
            return
        except Exception as error:
            with suppress(_StoppedError):
                send(error)

    worker = asyncio.create_task(asyncio.to_thread(generate))
    try:
        while True:
            item = await queue.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        stopped.set()
        await asyncio.shield(worker)
