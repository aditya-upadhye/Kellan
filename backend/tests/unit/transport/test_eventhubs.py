import asyncio
from typing import Any

from matchlens.models.envelope import StreamEnvelope
from matchlens.transport.eventhubs import EventHubsTransport


class FakeEventData:
    def __init__(self, body: str, properties: dict[str, str] | None = None) -> None:
        self.body = body
        self.properties = properties

    def body_as_str(self) -> str:
        return self.body


class FakeBatch:
    def __init__(self) -> None:
        self.events: list[FakeEventData] = []

    def add(self, event: FakeEventData) -> None:
        self.events.append(event)


class FakeProducer:
    def __init__(self) -> None:
        self.batch = FakeBatch()
        self.partition_key: str | None = None

    async def create_batch(self, *, partition_key: str) -> FakeBatch:
        self.partition_key = partition_key
        return self.batch

    async def send_batch(self, _: FakeBatch) -> None:
        pass


class FakeConsumer:
    def __init__(self, stale: FakeEventData, current: FakeEventData) -> None:
        self.stale = stale
        self.current = current

    async def receive(self, on_event: Any, *, starting_position: str) -> None:
        assert starting_position == "-1"
        await on_event(None, self.stale)
        await on_event(None, self.current)
        await asyncio.Event().wait()


class FakeTransport(EventHubsTransport):
    def __init__(self, consumer: FakeConsumer, producer: FakeProducer) -> None:
        self._replay_session = "current"
        self._event_data = FakeEventData
        self._producer = producer
        self._consumer = consumer


def test_replay_session_filters_stale_events_for_same_match() -> None:
    async def exercise() -> None:
        message = StreamEnvelope(kind="status", match_id="same-match", data={"state": "done"})
        producer = FakeProducer()
        transport = FakeTransport(
            FakeConsumer(
                FakeEventData(message.model_dump_json(), {"replay_session": "old"}),
                FakeEventData(message.model_dump_json(), {"replay_session": "current"}),
            ),
            producer,
        )
        await transport.publish(message)
        assert producer.partition_key == "same-match"
        assert producer.batch.events[0].properties == {"replay_session": "current"}
        subscription = transport.subscribe()
        assert await asyncio.wait_for(anext(subscription), timeout=1) == message
        await subscription.aclose()

    asyncio.run(exercise())
