"""Azure Cosmos DB adapter. Install the optional ``azure`` dependency group."""

from importlib import import_module
from typing import Any

from matchlens.models.metrics import MetricSnapshot, MetricWindow


class CosmosMetricStore:
    def __init__(
        self, endpoint: str, database: str = "matchlens", container: str = "metrics"
    ) -> None:
        # SDK API: https://learn.microsoft.com/python/api/azure-cosmos/azure.cosmos.aio.cosmosclient
        identity = import_module("azure.identity.aio")
        cosmos = import_module("azure.cosmos.aio")
        self._credential: Any = identity.DefaultAzureCredential()
        self._client: Any = cosmos.CosmosClient(endpoint, credential=self._credential)
        self._database_name = database
        self._container_name = container
        self._container: Any = None

    async def _ready(self) -> Any:
        if self._container is None:
            database = await self._client.create_database_if_not_exists(self._database_name)
            partition_key = import_module("azure.cosmos").PartitionKey(path="/match_id")
            self._container = await database.create_container_if_not_exists(
                id=self._container_name, partition_key=partition_key
            )
        return self._container

    async def put(self, match_id: str, snapshot: MetricSnapshot) -> None:
        container = await self._ready()
        await container.upsert_item(
            {
                "id": (
                    f"{snapshot.metric_id}|{snapshot.window}|{snapshot.as_of_seq}"
                    f"|{snapshot.clock.period}|{snapshot.clock.ms}"
                ),
                "match_id": match_id,
                **snapshot.model_dump(mode="json"),
            }
        )

    async def get(
        self,
        match_id: str,
        metric_id: str,
        as_of_seq: int | None = None,
        window: MetricWindow | None = None,
    ) -> MetricSnapshot | None:
        container = await self._ready()
        conditions = ["c.match_id = @match", "c.metric_id = @metric"]
        parameters: list[dict[str, str | int]] = [
            {"name": "@match", "value": match_id},
            {"name": "@metric", "value": metric_id},
        ]
        if as_of_seq is not None:
            conditions.append("c.as_of_seq <= @seq")
            parameters.append({"name": "@seq", "value": as_of_seq})
        if window is not None:
            conditions.append("c.window = @window")
            parameters.append({"name": "@window", "value": window})
        query = "SELECT * FROM c WHERE " + " AND ".join(conditions)
        records = [
            item
            async for item in container.query_items(
                query=query, parameters=parameters, partition_key=match_id
            )
        ]
        if not records:
            return None
        if window is None and any(item["window"] == "match" for item in records):
            records = [item for item in records if item["window"] == "match"]
        latest = max(
            records,
            key=lambda item: (item["as_of_seq"], item["clock"]["period"], item["clock"]["ms"]),
        )
        return MetricSnapshot.model_validate(
            {key: latest[key] for key in MetricSnapshot.model_fields}
        )

    async def latest(self, match_id: str) -> list[MetricSnapshot]:
        container = await self._ready()
        records = [
            item
            async for item in container.query_items(
                query="SELECT * FROM c WHERE c.match_id = @match",
                parameters=[{"name": "@match", "value": match_id}],
                partition_key=match_id,
            )
        ]
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for item in records:
            key = item["metric_id"], item["window"]
            if key not in latest or (
                item["as_of_seq"],
                item["clock"]["period"],
                item["clock"]["ms"],
            ) > (
                latest[key]["as_of_seq"],
                latest[key]["clock"]["period"],
                latest[key]["clock"]["ms"],
            ):
                latest[key] = item
        return [
            MetricSnapshot.model_validate({key: item[key] for key in MetricSnapshot.model_fields})
            for item in latest.values()
        ]

    async def close(self) -> None:
        await self._client.close()
        await self._credential.close()
