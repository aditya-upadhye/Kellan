import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from matchlens.api.app import create_app
from matchlens.api.matches import MatchSession, session_stream
from matchlens.models.cues import Recap
from matchlens.models.envelope import StreamEnvelope
from matchlens.profiles import DEFAULT_PROFILES
from support.agent_workflow import metadata


@pytest.fixture
def client() -> Iterator[tuple[TestClient, str]]:
    test_client = TestClient(create_app())
    session = MatchSession(metadata(), 10, DEFAULT_PROFILES[:2])
    session.recaps["analyst_en", "half"] = Recap(
        recap_id="recap-half",
        match_id=session.metadata.match_id,
        profile_id="analyst_en",
        kind="half",
        title="Halftime recap",
        paragraphs=["First.", "Second.", "Third."],
        key_moment_ids=[],
        claims=[],
        status="verified",
    )
    test_client.app.state.match_manager.sessions[session.metadata.match_id] = session
    try:
        yield test_client, session.metadata.match_id
    finally:
        test_client.close()


def test_recap_api_filters_by_profile_and_kind(client: tuple[TestClient, str]) -> None:
    test_client, match_id = client
    response = test_client.get(f"/api/matches/{match_id}/recap?profile_id=analyst_en&kind=half")

    assert response.status_code == 200, response.text
    assert [item["recap_id"] for item in response.json()["recaps"]] == ["recap-half"]


def test_recap_api_rejects_profiles_not_active_in_match(client: tuple[TestClient, str]) -> None:
    test_client, match_id = client
    response = test_client.get(f"/api/matches/{match_id}/recap?profile_id=casual_es")

    assert response.status_code == 422


def test_fault_control_arms_exactly_one_pending_injection(
    client: tuple[TestClient, str],
) -> None:
    test_client, match_id = client
    response = test_client.post(
        f"/api/matches/{match_id}/control",
        json={"action": "inject_fault", "enabled": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["fault_inject_next"] is True


def test_recap_stream_replays_only_selected_profile() -> None:
    async def run() -> None:
        session = MatchSession(metadata(), 10, DEFAULT_PROFILES[:2], state="complete")
        for profile_id in ("analyst_en", "casual_en"):
            recap = Recap(
                recap_id=f"recap-{profile_id}",
                match_id=session.metadata.match_id,
                profile_id=profile_id,
                kind="half",
                title="Halftime recap",
                paragraphs=["First.", "Second.", "Third."],
                key_moment_ids=[],
                claims=[],
                status="verified",
            )
            session.publish_nowait(
                StreamEnvelope(
                    kind="recap",
                    match_id=session.metadata.match_id,
                    data=recap.model_dump(mode="json"),
                )
            )

        messages = [message async for message in session_stream(session, frozenset({"casual_en"}))]

        assert [message.data["profile_id"] for message in messages if message.kind == "recap"] == [
            "casual_en"
        ]

    asyncio.run(run())
