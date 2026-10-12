import asyncio

import pytest

from matchlens.store.memory import MemoryMetricStore
from support.agent_workflow import metadata, metric


def test_metric_view_pins_same_sequence_updates_and_rejects_writes() -> None:
    async def run() -> None:
        store = MemoryMetricStore()
        match_id = metadata().match_id
        first = metric(1)
        await store.put(match_id, first)
        view = store.snapshot()
        await store.put(match_id, metric(2))
        await store.put(match_id, metric(3, seq=2))
        assert await view.get(match_id, first.metric_id, 1) == first
        assert await view.get(match_id, first.metric_id) == first
        assert await view.snapshot().latest(match_id) == [first]
        assert await store.get(match_id, first.metric_id, 1) == metric(2)
        with pytest.raises(TypeError, match="read-only"):
            await view.put(match_id, metric(4, seq=3))

    asyncio.run(run())
