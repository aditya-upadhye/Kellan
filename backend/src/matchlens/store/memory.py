from bisect import bisect_right
from collections import defaultdict

from matchlens.models.metrics import MetricSnapshot, MetricWindow


class MemoryMetricStore:
    def __init__(self) -> None:
        self._history: dict[tuple[str, str], list[MetricSnapshot]] = defaultdict(list)
        self._limits: dict[tuple[str, str], int] | None = None

    def snapshot(self) -> "MemoryMetricStore":
        view = MemoryMetricStore()
        view._history = self._history.copy()
        view._limits = (
            self._limits.copy()
            if self._limits is not None
            else {key: len(history) for key, history in self._history.items()}
        )
        return view

    async def put(self, match_id: str, snapshot: MetricSnapshot) -> None:
        if self._limits is not None:
            raise TypeError("metric snapshots are read-only")
        history = self._history[match_id, snapshot.metric_id]
        if history and snapshot.as_of_seq < history[-1].as_of_seq:
            raise ValueError("metric snapshots must be inserted in sequence order")
        history.append(snapshot)

    async def get(
        self,
        match_id: str,
        metric_id: str,
        as_of_seq: int | None = None,
        window: MetricWindow | None = None,
    ) -> MetricSnapshot | None:
        history = self._history.get((match_id, metric_id), [])
        limit = len(history) if self._limits is None else self._limits.get((match_id, metric_id), 0)
        if not history:
            return None
        index = (
            limit
            if as_of_seq is None
            else bisect_right(history, as_of_seq, hi=limit, key=lambda item: item.as_of_seq)
        )
        if window is None:
            window = "match"
            if not any(item.window == window for item in history[:index]):
                return history[index - 1] if index else None
        return next(
            (
                history[position]
                for position in range(index - 1, -1, -1)
                if history[position].window == window
            ),
            None,
        )

    async def latest(self, match_id: str) -> list[MetricSnapshot]:
        latest: dict[tuple[str, MetricWindow], MetricSnapshot] = {}
        for (mid, metric_id), history in self._history.items():
            if mid == match_id:
                limit = len(history) if self._limits is None else self._limits[mid, metric_id]
                for item in history[:limit]:
                    latest[metric_id, item.window] = item
        return list(latest.values())

    async def close(self) -> None:
        pass
