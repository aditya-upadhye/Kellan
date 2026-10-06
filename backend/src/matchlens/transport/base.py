from collections.abc import AsyncIterator
from typing import Protocol

from matchlens.models.envelope import StreamEnvelope


class MatchTransport(Protocol):
    async def publish(self, message: StreamEnvelope) -> None: ...

    def subscribe(self) -> AsyncIterator[StreamEnvelope]: ...

    async def close(self) -> None: ...
