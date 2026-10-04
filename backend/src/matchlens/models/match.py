from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, field_validator, model_validator

from matchlens.models.base import Contract, Identifier, PlayerId, TeamSide

SQUAD_SIZE = 18
STARTERS_PER_TEAM = 11
OUTFIELD_STARTERS = STARTERS_PER_TEAM - 1

Position = Literal["GK", "DF", "MF", "FW"]
Role = Literal["GK", "CB", "FB", "DM", "CM", "AM", "W", "ST"]
HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]
Rating = Annotated[int, Field(ge=0, le=100)]
StyleWeight = Annotated[float, Field(ge=0.0, le=1.0)]


class PlayerTraits(Contract):
    pace: Rating
    passing: Rating
    finishing: Rating
    defending: Rating


class Player(Contract):
    player_id: PlayerId
    name: str = Field(min_length=1, max_length=40)
    number: int = Field(ge=1, le=99)
    position: Position
    role: Role
    traits: PlayerTraits
    starter: bool


class TeamColors(Contract):
    primary: HexColor
    secondary: HexColor


class TeamStyle(Contract):
    possession: StyleWeight
    press: StyleWeight
    directness: StyleWeight


class Team(Contract):
    team_id: TeamSide
    name: str = Field(min_length=1, max_length=40)
    short_name: str = Field(pattern=r"^[A-Z]{3}$")
    colors: TeamColors
    formation: str = Field(pattern=r"^[1-9](-[1-9]){2,3}$")
    style: TeamStyle
    players: list[Player] = Field(min_length=SQUAD_SIZE, max_length=SQUAD_SIZE)

    @field_validator("formation")
    @classmethod
    def formation_fields_ten_outfield_players(cls, formation: str) -> str:
        if sum(int(line) for line in formation.split("-")) != OUTFIELD_STARTERS:
            raise ValueError(f"formation {formation} must add up to {OUTFIELD_STARTERS}")
        return formation

    @model_validator(mode="after")
    def player_ids_match_side_and_number(self) -> Self:
        side_prefix = self.team_id[0]
        for player in self.players:
            expected_id = f"{side_prefix}{player.number:02d}"
            if player.player_id != expected_id:
                raise ValueError(f"player {player.player_id} must have id {expected_id}")
        if len({player.number for player in self.players}) != SQUAD_SIZE:
            raise ValueError("shirt numbers must be unique")
        return self

    @model_validator(mode="after")
    def starting_eleven_has_one_goalkeeper(self) -> Self:
        starters = [player for player in self.players if player.starter]
        if len(starters) != STARTERS_PER_TEAM:
            raise ValueError(f"expected {STARTERS_PER_TEAM} starters, got {len(starters)}")
        if sum(player.position == "GK" for player in starters) != 1:
            raise ValueError("the starting eleven needs exactly one goalkeeper")
        return self


class MatchMetadata(Contract):
    match_id: Identifier
    competition: str = Field(min_length=1, max_length=60)
    venue: str = Field(min_length=1, max_length=60)
    home: Team
    away: Team
    scenario: Identifier
    seed: int = Field(ge=0)

    @model_validator(mode="after")
    def teams_play_their_assigned_sides(self) -> Self:
        if self.home.team_id != "home" or self.away.team_id != "away":
            raise ValueError("home and away teams must have team_id 'home' and 'away'")
        if self.home.name == self.away.name:
            raise ValueError("a club cannot play itself")
        return self
