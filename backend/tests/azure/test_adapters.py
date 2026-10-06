"""Live adapter checks. Run with ``pytest -m azure`` and Azure credentials."""

import asyncio
import os
import uuid

import pytest

from matchlens.models.clock import MatchClock
from matchlens.models.envelope import StreamEnvelope
from matchlens.models.metrics import MetricSnapshot
from matchlens.store.cosmos import CosmosMetricStore
from matchlens.transport.eventhubs import EventHubsTransport


@pytest.mark.azure
def test_eventhubs_round_trip() -> None:
    fqdn = os.getenv("EVENTHUBS_FQDN")
    if not fqdn:
        pytest.skip("EVENTHUBS_FQDN is not configured")
    match_id = f"azure-test-{uuid.uuid4().hex[:12]}"

    async def exercise() -> None:
        name = os.getenv("EVENTHUBS_NAME", "matchlens")
        old = EventHubsTransport(fqdn, name, replay_session=uuid.uuid4().hex)
        transport = EventHubsTransport(fqdn, name, replay_session=uuid.uuid4().hex)
        expected = StreamEnvelope(kind="status", match_id=match_id, data={"state": "ping"})

        async def receive() -> StreamEnvelope:
            async for message in transport.subscribe():
                if message.match_id == match_id:
                    return message
            raise AssertionError("consumer stopped before message arrived")

        task = asyncio.create_task(receive())
        try:
            await old.publish(
                StreamEnvelope(kind="status", match_id=match_id, data={"state": "stale"})
            )
            await transport.publish(expected)
            assert await asyncio.wait_for(task, timeout=30) == expected
        finally:
            task.cancel()
            await transport.close()
            await old.close()

    asyncio.run(exercise())


@pytest.mark.azure
def test_cosmos_historical_lookup() -> None:
    endpoint = os.getenv("COSMOS_ENDPOINT")
    if not endpoint:
        pytest.skip("COSMOS_ENDPOINT is not configured")
    match_id = f"azure-test-{uuid.uuid4().hex[:12]}"

    async def exercise() -> None:
        store = CosmosMetricStore(
            endpoint,
            os.getenv("COSMOS_DATABASE", "matchlens"),
            os.getenv("COSMOS_CONTAINER", "metrics"),
        )
        try:
            for seq, value in ((2, 1), (5, 2)):
                await store.put(
                    match_id,
                    MetricSnapshot(
                        metric_id="team.home.goals",
                        scope="team",
                        subject_id="home",
                        label="Goals",
                        value=value,
                        unit="count",
                        window="match",
                        as_of_seq=seq,
                        clock=MatchClock(period=1, ms=seq * 1000),
                    ),
                )
            historical = await store.get(match_id, "team.home.goals", 3)
            latest = await store.get(match_id, "team.home.goals")
            assert historical is not None
            assert historical.value == 1
            assert latest is not None
            assert latest.value == 2
            assert any(item.metric_id == "team.home.goals" for item in await store.latest(match_id))
        finally:
            await store.close()

    asyncio.run(exercise())
