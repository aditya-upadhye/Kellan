from typing import Protocol

from matchlens.models.metrics import MetricSnapshot, MetricWindow


class MetricStore(Protocol):
    async def put(self, match_id: str, snapshot: MetricSnapshot) -> None: ...

    async def get(
        self,
        match_id: str,
        metric_id: str,
        as_of_seq: int | None = None,
        window: MetricWindow | None = None,
    ) -> MetricSnapshot | None: ...

    async def latest(self, match_id: str) -> list[MetricSnapshot]: ...

    async def close(self) -> None: ...
