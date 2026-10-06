import asyncio

from matchlens.store.cosmos import CosmosMetricStore


class FakeDatabase:
    def __init__(self) -> None:
        self.container_name: str | None = None
        self.container = object()

    def get_container_client(self, name: str) -> object:
        self.container_name = name
        return self.container


class FakeClient:
    def __init__(self, database: FakeDatabase) -> None:
        self.database = database
        self.database_name: str | None = None

    def get_database_client(self, name: str) -> FakeDatabase:
        self.database_name = name
        return self.database


class FakeCosmosMetricStore(CosmosMetricStore):
    def __init__(self, client: FakeClient) -> None:
        self._client = client
        self._database_name = "matchlens"
        self._container_name = "metrics"
        self._container = None

    async def ready(self) -> object:
        return await self._ready()


def test_cosmos_store_uses_preprovisioned_container() -> None:
    async def exercise() -> None:
        database = FakeDatabase()
        client = FakeClient(database)
        store = FakeCosmosMetricStore(client)

        assert await store.ready() is database.container
        assert client.database_name == "matchlens"
        assert database.container_name == "metrics"

    asyncio.run(exercise())
