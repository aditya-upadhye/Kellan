from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from matchlens.api.app import create_app
from matchlens.profiles import DEFAULT_PROFILES


@pytest.fixture
def client() -> Iterator[TestClient]:
    client = TestClient(create_app())
    try:
        yield client
    finally:
        client.close()


def test_default_profiles_cover_personalization_modes() -> None:
    assert [profile.profile_id for profile in DEFAULT_PROFILES] == [
        "analyst_en",
        "casual_en",
        "casual_es",
        "player_focus",
    ]
    assert DEFAULT_PROFILES[0].mode == "analyst"
    assert DEFAULT_PROFILES[1].mode == DEFAULT_PROFILES[2].mode == "casual"
    assert DEFAULT_PROFILES[1].language == "en"
    assert DEFAULT_PROFILES[2].language == "es"
    assert DEFAULT_PROFILES[3].favorite_player_id == "h09"
    assert DEFAULT_PROFILES[3].label == "Home No. 9"


def test_profile_api_lists_seed_profiles(client: TestClient) -> None:
    response = client.get("/api/profiles")

    assert response.status_code == 200
    assert [profile["profile_id"] for profile in response.json()] == [
        "analyst_en",
        "casual_en",
        "casual_es",
        "player_focus",
    ]


def test_profile_api_returns_profile_by_id(client: TestClient) -> None:
    response = client.get("/api/profiles/casual_es")

    assert response.status_code == 200
    assert response.json()["language"] == "es"
    assert response.json()["mode"] == "casual"


def test_profile_api_returns_not_found_for_unknown_id(client: TestClient) -> None:
    response = client.get("/api/profiles/unknown")

    assert response.status_code == 404
