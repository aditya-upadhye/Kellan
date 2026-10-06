import asyncio
from collections.abc import AsyncIterator

from matchlens.models.envelope import StreamEnvelope


class LocalTransport:
    """FIFO stream for one local consumer; backpressure is provided by the queue."""

    def __init__(self, *, maxsize: int = 1024) -> None:
        self._queue: asyncio.Queue[StreamEnvelope | None] = asyncio.Queue(maxsize=maxsize)
        self._closed = False

    async def publish(self, message: StreamEnvelope) -> None:
        if self._closed:
            raise RuntimeError("transport is closed")
        await self._queue.put(message)

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._queue.put(None)

    async def subscribe(self) -> AsyncIterator[StreamEnvelope]:
        while (message := await self._queue.get()) is not None:
            yield message
