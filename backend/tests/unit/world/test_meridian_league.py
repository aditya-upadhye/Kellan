from statistics import mean
from typing import Any

import pytest
from pydantic import ValidationError

from matchlens.models.base import TeamSide
from matchlens.world.formations import FORMATION_ROLES
from matchlens.world.meridian import KESTREL_BAY, MERIDIAN_LEAGUE
from matchlens.world.models import Club, League, UnknownClubError

CLUBS = MERIDIAN_LEAGUE.clubs


def club_payload(**changes: Any) -> dict[str, Any]:
    return KESTREL_BAY.model_dump() | changes


def test_league_has_four_clubs_and_seventy_two_players() -> None:
    assert len(CLUBS) == 4
    assert sum(len(club.squad) for club in CLUBS) == 72


@pytest.mark.parametrize("club", CLUBS, ids=lambda club: club.short_name)
@pytest.mark.parametrize("side", ["home", "away"])
def test_every_club_fields_a_valid_team_on_either_side(club: Club, side: TeamSide) -> None:
    team = club.as_team(side)

    assert team.name == club.name
    assert [player.player_id[0] for player in team.players] == [side[0]] * 18
    assert [player.role for player in team.players if player.starter] == list(
        FORMATION_ROLES[club.formation]
    )


def test_clubs_span_contrasting_styles() -> None:
    most_possession = max(CLUBS, key=lambda club: club.style.possession)
    most_pressing = max(CLUBS, key=lambda club: club.style.press)
    most_direct = max(CLUBS, key=lambda club: club.style.directness)

    assert len({most_possession.club_id, most_pressing.club_id, most_direct.club_id}) == 3


@pytest.mark.parametrize("club", CLUBS, ids=lambda club: club.short_name)
def test_ratings_fit_player_roles(club: Club) -> None:
    def average(role_group: set[str], trait: str) -> float:
        players = [player for player in club.squad if player.role in role_group]
        return mean(getattr(player.traits, trait) for player in players)

    assert average({"ST", "W"}, "finishing") > average({"CB", "FB"}, "finishing")
    assert average({"CB", "FB"}, "defending") > average({"ST", "W"}, "defending")
    assert average({"DM", "CM", "AM"}, "passing") > average({"CB"}, "passing")
    assert average({"GK"}, "finishing") < 20


def test_finds_club_by_id() -> None:
    assert MERIDIAN_LEAGUE.club("port-halden").short_name == "PHF"


def test_unknown_club_id_raises() -> None:
    with pytest.raises(UnknownClubError, match="no club with id 'atlantis'"):
        MERIDIAN_LEAGUE.club("atlantis")


def test_rejects_starters_out_of_formation_order() -> None:
    starters = list(KESTREL_BAY.model_dump()["starters"])
    starters[1], starters[2] = starters[2], starters[1]

    with pytest.raises(ValidationError, match="don't fit formation 4-3-3"):
        Club.model_validate(club_payload(starters=starters))


def test_rejects_bench_without_goalkeeper() -> None:
    bench = KESTREL_BAY.model_dump()["bench"]
    bench[0]["role"] = "CB"

    with pytest.raises(ValidationError, match="bench needs exactly one goalkeeper"):
        Club.model_validate(club_payload(bench=bench))


def test_rejects_duplicate_shirt_numbers() -> None:
    bench = KESTREL_BAY.model_dump()["bench"]
    bench[1]["number"] = 4

    with pytest.raises(ValidationError, match="duplicate shirt numbers"):
        Club.model_validate(club_payload(bench=bench))


def test_league_rejects_duplicate_player_names() -> None:
    reserves = Club.model_validate(
        club_payload(
            club_id="kestrel-reserves",
            name="Kestrel Bay Reserves",
            short_name="KBR",
            venue="Gullwing Annex",
        )
    )

    with pytest.raises(ValidationError, match="player names must be unique"):
        League(name="Test League", clubs=(*CLUBS, reserves))


def test_league_rejects_clubs_sharing_a_short_name() -> None:
    twin = Club.model_validate(
        club_payload(club_id="kestrel-twin", name="Kestrel Twin", venue="Twin Park")
    )

    with pytest.raises(ValidationError, match="unique short_name"):
        League(name="Test League", clubs=(*CLUBS, twin))
