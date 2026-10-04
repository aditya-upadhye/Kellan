from typing import Self

from pydantic import Field, model_validator

from matchlens.models.base import Contract, Identifier, TeamSide
from matchlens.models.match import (
    SQUAD_SIZE,
    STARTERS_PER_TEAM,
    Player,
    PlayerTraits,
    Position,
    Role,
    Team,
    TeamColors,
    TeamStyle,
)
from matchlens.world.formations import FORMATION_ROLES, POSITION_BY_ROLE, Formation

BENCH_SIZE = SQUAD_SIZE - STARTERS_PER_TEAM


class UnknownClubError(LookupError):
    pass


class SquadPlayer(Contract):
    number: int = Field(ge=1, le=99)
    name: str = Field(min_length=1, max_length=40)
    role: Role
    traits: PlayerTraits

    @property
    def position(self) -> Position:
        return POSITION_BY_ROLE[self.role]


class Club(Contract):
    club_id: Identifier
    name: str = Field(min_length=1, max_length=40)
    short_name: str = Field(pattern=r"^[A-Z]{3}$")
    venue: str = Field(min_length=1, max_length=60)
    colors: TeamColors
    formation: Formation
    style: TeamStyle
    starters: tuple[SquadPlayer, ...] = Field(
        min_length=STARTERS_PER_TEAM, max_length=STARTERS_PER_TEAM
    )
    bench: tuple[SquadPlayer, ...] = Field(min_length=BENCH_SIZE, max_length=BENCH_SIZE)

    @model_validator(mode="after")
    def starters_line_up_in_formation_order(self) -> Self:
        starter_roles = tuple(player.role for player in self.starters)
        if starter_roles != FORMATION_ROLES[self.formation]:
            raise ValueError(
                f"{self.name} starters {starter_roles} don't fit formation {self.formation}"
            )
        return self

    @model_validator(mode="after")
    def bench_carries_one_goalkeeper(self) -> Self:
        if sum(player.role == "GK" for player in self.bench) != 1:
            raise ValueError(f"{self.name} bench needs exactly one goalkeeper")
        return self

    @model_validator(mode="after")
    def shirt_numbers_are_unique(self) -> Self:
        if len({player.number for player in self.squad}) != SQUAD_SIZE:
            raise ValueError(f"{self.name} has duplicate shirt numbers")
        return self

    @property
    def squad(self) -> tuple[SquadPlayer, ...]:
        return self.starters + self.bench

    def as_team(self, side: TeamSide) -> Team:
        players = [
            self._as_player(squad_player, side, starter=True) for squad_player in self.starters
        ] + [self._as_player(squad_player, side, starter=False) for squad_player in self.bench]
        return Team(
            team_id=side,
            name=self.name,
            short_name=self.short_name,
            colors=self.colors,
            formation=self.formation,
            style=self.style,
            players=players,
        )

    @staticmethod
    def _as_player(squad_player: SquadPlayer, side: TeamSide, *, starter: bool) -> Player:
        return Player(
            player_id=f"{side[0]}{squad_player.number:02d}",
            name=squad_player.name,
            number=squad_player.number,
            position=squad_player.position,
            role=squad_player.role,
            traits=squad_player.traits,
            starter=starter,
        )


class League(Contract):
    name: str = Field(min_length=1, max_length=60)
    clubs: tuple[Club, ...] = Field(min_length=4)

    @model_validator(mode="after")
    def clubs_are_distinguishable(self) -> Self:
        for attribute in ("club_id", "name", "short_name", "venue"):
            values = [getattr(club, attribute) for club in self.clubs]
            if len(set(values)) != len(values):
                raise ValueError(f"clubs must have unique {attribute} values")
        return self

    @model_validator(mode="after")
    def player_names_are_unique(self) -> Self:
        names = [player.name for club in self.clubs for player in club.squad]
        if len(set(names)) != len(names):
            raise ValueError("player names must be unique across the league")
        return self

    def club(self, club_id: str) -> Club:
        for club in self.clubs:
            if club.club_id == club_id:
                return club
        raise UnknownClubError(f"no club with id {club_id!r} in {self.name}")
