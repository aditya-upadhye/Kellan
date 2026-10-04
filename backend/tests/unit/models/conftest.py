import pytest

from matchlens.models.base import TeamSide
from matchlens.models.match import (
    Player,
    PlayerTraits,
    Position,
    Role,
    Team,
    TeamColors,
    TeamStyle,
)

SQUAD_LAYOUT: list[tuple[Position, Role, bool]] = [
    ("GK", "GK", True),
    ("DF", "FB", True),
    ("DF", "CB", True),
    ("DF", "CB", True),
    ("DF", "FB", True),
    ("MF", "DM", True),
    ("MF", "CM", True),
    ("MF", "CM", True),
    ("FW", "W", True),
    ("FW", "ST", True),
    ("FW", "W", True),
    ("GK", "GK", False),
    ("DF", "CB", False),
    ("DF", "FB", False),
    ("MF", "CM", False),
    ("MF", "AM", False),
    ("FW", "W", False),
    ("FW", "ST", False),
]


def build_team(side: TeamSide, name: str) -> Team:
    players = [
        Player(
            player_id=f"{side[0]}{number:02d}",
            name=f"{name} Player {number}",
            number=number,
            position=position,
            role=role,
            traits=PlayerTraits(pace=70, passing=70, finishing=60, defending=60),
            starter=starter,
        )
        for number, (position, role, starter) in enumerate(SQUAD_LAYOUT, start=1)
    ]
    return Team(
        team_id=side,
        name=name,
        short_name=name[:3].upper(),
        colors=TeamColors(primary="#1F4E79", secondary="#FFFFFF"),
        formation="4-3-3",
        style=TeamStyle(possession=0.6, press=0.5, directness=0.4),
        players=players,
    )


@pytest.fixture
def home_team() -> Team:
    return build_team("home", "Harbor City")


@pytest.fixture
def away_team() -> Team:
    return build_team("away", "Northvale")
