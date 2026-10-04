from typing import Any

import pytest
from pydantic import ValidationError

from matchlens.models.match import MatchMetadata, Team


def team_payload(team: Team) -> dict[str, Any]:
    return team.model_dump()


def test_valid_team_has_eleven_starters(home_team: Team) -> None:
    assert sum(player.starter for player in home_team.players) == 11


def test_rejects_formation_without_ten_outfield_players(home_team: Team) -> None:
    payload = team_payload(home_team) | {"formation": "4-4-3"}

    with pytest.raises(ValidationError, match="must add up to 10"):
        Team.model_validate(payload)


def test_rejects_player_id_not_matching_side_and_number(home_team: Team) -> None:
    payload = team_payload(home_team)
    payload["players"][3]["player_id"] = "a04"

    with pytest.raises(ValidationError, match="must have id h04"):
        Team.model_validate(payload)


def test_rejects_duplicate_shirt_numbers(home_team: Team) -> None:
    payload = team_payload(home_team)
    payload["players"][17] |= {"number": 1, "player_id": "h01"}

    with pytest.raises(ValidationError, match="unique"):
        Team.model_validate(payload)


def test_rejects_starting_eleven_with_two_goalkeepers(home_team: Team) -> None:
    payload = team_payload(home_team)
    payload["players"][10]["starter"] = False
    payload["players"][11]["starter"] = True

    with pytest.raises(ValidationError, match="exactly one goalkeeper"):
        Team.model_validate(payload)


def test_rejects_squad_with_ten_starters(home_team: Team) -> None:
    payload = team_payload(home_team)
    payload["players"][10]["starter"] = False

    with pytest.raises(ValidationError, match="expected 11 starters"):
        Team.model_validate(payload)


def build_metadata(home: Team, away: Team) -> MatchMetadata:
    return MatchMetadata(
        match_id="balanced-s42",
        competition="Coastal Premier Division",
        venue="Lighthouse Park",
        home=home,
        away=away,
        scenario="balanced",
        seed=42,
    )


def test_metadata_accepts_teams_on_their_sides(home_team: Team, away_team: Team) -> None:
    assert build_metadata(home_team, away_team).home.team_id == "home"


def test_metadata_rejects_swapped_sides(home_team: Team, away_team: Team) -> None:
    with pytest.raises(ValidationError, match="team_id 'home' and 'away'"):
        build_metadata(away_team, home_team)
