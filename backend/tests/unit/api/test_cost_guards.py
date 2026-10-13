import asyncio
from collections.abc import Iterator
from typing import cast

import pytest
from fastapi.testclient import TestClient

from matchlens.api.app import create_app
from matchlens.api.matches import (
    MatchCapacityError,
    MatchManager,
    MatchSession,
    StartMatchRequest,
)
from matchlens.config import Settings
from matchlens.profiles import DEFAULT_PROFILES
from matchlens.sim.scenarios import Injection
from support.agent_workflow import metadata


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, MatchManager]]:
    async def finish_match(_: MatchManager, session: MatchSession, __: list[Injection]) -> None:
        session.state = "complete"

    monkeypatch.setattr(MatchManager, "_run", finish_match)
    app = create_app(Settings(max_match_starts_per_ip_per_hour=1))
    test_client = TestClient(app)
    try:
        yield test_client, cast("MatchManager", app.state.match_manager)
    finally:
        test_client.close()


def test_match_start_rate_limit_is_per_ip_and_returns_retry_after(
    client: tuple[TestClient, MatchManager],
) -> None:
    test_client, _ = client
    first = test_client.post(
        "/api/matches",
        json={"scenario": "balanced", "seed": 1},
        headers={"X-MatchLens-Client-IP": "198.51.100.7"},
    )
    second = test_client.post(
        "/api/matches",
        json={"scenario": "balanced", "seed": 2},
        headers={"X-MatchLens-Client-IP": "198.51.100.8"},
    )

    assert first.status_code == 202
    assert second.status_code == 429
    assert int(second.headers["retry-after"]) > 0


def test_trusted_proxy_address_drives_per_ip_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def finish_match(_: MatchManager, session: MatchSession, __: list[Injection]) -> None:
        session.state = "complete"

    monkeypatch.setattr(MatchManager, "_run", finish_match)
    test_client = TestClient(
        create_app(Settings(max_match_starts_per_ip_per_hour=1, trust_proxy_client_ip=True))
    )
    first = test_client.post(
        "/api/matches",
        json={"scenario": "balanced"},
        headers={"X-MatchLens-Client-IP": "198.51.100.7"},
    )
    other_ip = test_client.post(
        "/api/matches",
        json={"scenario": "balanced"},
        headers={"X-MatchLens-Client-IP": "198.51.100.8"},
    )
    repeated_ip = test_client.post(
        "/api/matches",
        json={"scenario": "balanced"},
        headers={"X-MatchLens-Client-IP": "198.51.100.7"},
    )
    test_client.close()

    assert first.status_code == other_ip.status_code == 202
    assert repeated_ip.status_code == 429


def test_judge_mode_overrides_match_request_with_fixed_preset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def finish_match(_: MatchManager, session: MatchSession, __: list[Injection]) -> None:
        session.state = "complete"

    monkeypatch.setattr(MatchManager, "_run", finish_match)
    app = create_app(Settings(judge_mode=True))
    test_client = TestClient(app)
    assert test_client.get("/api/config").json() == {"judge_mode": True}
    response = test_client.post(
        "/api/matches",
        json={"scenario": "balanced", "seed": 99, "speed": 1, "profiles": ["analyst_en"]},
    )
    assert response.status_code == 202
    session = cast("MatchManager", app.state.match_manager).get(response.json()["match_id"])
    test_client.close()

    assert session.metadata.scenario == "late_comeback"
    assert session.metadata.seed == 1
    assert session.speed == 10
    assert session.profiles == DEFAULT_PROFILES


def test_match_manager_rejects_start_when_capacity_is_full() -> None:
    async def run() -> None:
        manager = MatchManager(Settings(max_concurrent_matches=1))
        session = MatchSession(metadata(), 10, state="running")
        manager.sessions[session.metadata.match_id] = session
        with pytest.raises(MatchCapacityError):
            await manager.start(StartMatchRequest(), "192.0.2.1")
        await manager.close()

    asyncio.run(run())


def test_match_stops_after_idle_timeout_without_viewers(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        async def wait_for_cancel(_: MatchManager, __: MatchSession, ___: list[Injection]) -> None:
            await asyncio.Event().wait()

        monkeypatch.setattr(MatchManager, "_run", wait_for_cancel)
        manager = MatchManager(Settings(match_idle_timeout_seconds=0.01))
        session = await manager.start(StartMatchRequest(), "192.0.2.1")
        assert session.idle_task is not None
        await session.idle_task
        assert session.state == "stopped"
        assert session.error == "Match stopped after no viewers were connected"
        await manager.close()

    asyncio.run(run())
