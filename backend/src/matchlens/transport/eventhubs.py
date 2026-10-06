"""Azure Event Hubs adapter. Install the optional ``azure`` dependency group."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import suppress
from importlib import import_module
from typing import Any, cast

from matchlens.models.envelope import StreamEnvelope


class EventHubsTransport:
    def __init__(
        self,
        fqdn: str,
        name: str,
        consumer_group: str = "$Default",
        *,
        replay_session: str | None = None,
    ) -> None:
        # SDK API: https://learn.microsoft.com/python/api/azure-eventhub/azure.eventhub.aio.eventhubproducerclient
        # and https://learn.microsoft.com/python/api/azure-eventhub/azure.eventhub.aio.eventhubconsumerclient
        identity = import_module("azure.identity.aio")
        eventhub = import_module("azure.eventhub.aio")
        self._event_data = import_module("azure.eventhub").EventData
        self._replay_session = replay_session
        self._credential: Any = identity.DefaultAzureCredential()
        self._producer: Any = eventhub.EventHubProducerClient(
            fully_qualified_namespace=fqdn, eventhub_name=name, credential=self._credential
        )
        self._consumer: Any = eventhub.EventHubConsumerClient(
            fully_qualified_namespace=fqdn,
            eventhub_name=name,
            consumer_group=consumer_group,
            credential=self._credential,
        )

    async def publish(self, message: StreamEnvelope) -> None:
        batch = await self._producer.create_batch(partition_key=message.match_id)
        event = self._event_data(message.model_dump_json())
        if self._replay_session is not None:
            # Application properties: https://learn.microsoft.com/python/api/azure-eventhub/azure.eventhub.eventdata
            event.properties = {"replay_session": self._replay_session}
        batch.add(event)
        await self._producer.send_batch(batch)

    async def subscribe(self) -> AsyncGenerator[StreamEnvelope, None]:
        queue: asyncio.Queue[StreamEnvelope] = asyncio.Queue(maxsize=1024)
        errors: asyncio.Queue[Exception] = asyncio.Queue(maxsize=1)

        async def on_event(_: Any, event: Any) -> None:
            if event is not None:
                if self._replay_session is not None:
                    properties = cast("dict[str | bytes, str | bytes]", event.properties or {})
                    session = properties.get("replay_session") or properties.get(b"replay_session")
                    if isinstance(session, bytes):
                        session = session.decode()
                    if session != self._replay_session:
                        return
                await queue.put(StreamEnvelope.model_validate_json(event.body_as_str()))

        async def on_error(_: Any, error: Exception) -> None:
            if errors.empty():
                await errors.put(error)

        task = asyncio.create_task(
            self._consumer.receive(on_event, on_error=on_error, starting_position="-1")
        )
        next_message: asyncio.Task[StreamEnvelope] | None = None
        next_error: asyncio.Task[Exception] | None = None
        try:
            while True:
                next_message = asyncio.create_task(queue.get())
                next_error = asyncio.create_task(errors.get())
                done, _ = await asyncio.wait(
                    {task, next_message, next_error}, return_when=asyncio.FIRST_COMPLETED
                )
                if next_message in done:
                    next_error.cancel()
                    yield next_message.result()
                elif next_error in done:
                    next_message.cancel()
                    raise next_error.result()
                else:
                    next_message.cancel()
                    next_error.cancel()
                if task in done:
                    task.result()
                    raise RuntimeError("Event Hubs consumer stopped")
        finally:
            if next_message is not None:
                next_message.cancel()
            if next_error is not None:
                next_error.cancel()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def close(self) -> None:
        await self._producer.close()
        await self._consumer.close()
        await self._credential.close()
