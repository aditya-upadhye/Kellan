from typing import Literal, Self

from pydantic import Field, model_validator

from matchlens.models.base import Contract, Identifier, Language, PlayerId, TeamSide

ViewerMode = Literal["analyst", "casual", "player_focus"]
Verbosity = Literal["short", "standard", "detailed"]


class ViewerProfile(Contract):
    profile_id: Identifier
    label: str = Field(min_length=1, max_length=40)
    mode: ViewerMode
    language: Language
    favorite_team_id: TeamSide | None
    favorite_player_id: PlayerId | None
    focus_metric: str | None = Field(
        max_length=64, pattern=r"^(match|team|player|event)(\.[A-Za-z0-9_-]+)*$"
    )
    verbosity: Verbosity

    @model_validator(mode="after")
    def player_focus_names_a_player(self) -> Self:
        if self.mode == "player_focus" and self.favorite_player_id is None:
            raise ValueError("player_focus profiles need a favorite_player_id")
        return self
