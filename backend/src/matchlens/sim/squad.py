from dataclasses import dataclass, field

from matchlens.models.match import Player, Team
from matchlens.world.formations import Anchor, formation_anchors


@dataclass(slots=True)
class PlayerState:
    player: Player
    slot: int | None
    has_played: bool
    yellow_cards: int = 0
    sent_off: bool = False

    @property
    def player_id(self) -> str:
        return self.player.player_id

    @property
    def on_pitch(self) -> bool:
        return self.slot is not None and not self.sent_off

    @property
    def is_goalkeeper(self) -> bool:
        return self.player.role == "GK"


@dataclass(slots=True)
class TeamState:
    team: Team
    anchors: tuple[Anchor, ...]
    players: list[PlayerState]
    substitution_times_ms: list[int] = field(default_factory=list[int])

    @classmethod
    def from_team(cls, team: Team) -> "TeamState":
        starters = [player for player in team.players if player.starter]
        substitutes = [player for player in team.players if not player.starter]
        players = [
            PlayerState(player=player, slot=slot, has_played=True)
            for slot, player in enumerate(starters)
        ] + [PlayerState(player=player, slot=None, has_played=False) for player in substitutes]
        return cls(team=team, anchors=formation_anchors(team.formation), players=players)

    def player(self, player_id: str) -> PlayerState:
        return next(player for player in self.players if player.player_id == player_id)

    def on_pitch(self) -> list[PlayerState]:
        return [player for player in self.players if player.on_pitch]

    def outfield(self) -> list[PlayerState]:
        return [player for player in self.on_pitch() if not player.is_goalkeeper]

    def goalkeeper(self) -> PlayerState:
        return next(player for player in self.on_pitch() if player.is_goalkeeper)

    def available_substitutes(self) -> list[PlayerState]:
        return [
            player for player in self.players if not player.has_played and not player.is_goalkeeper
        ]

    def most_advanced(self) -> PlayerState:
        return max(self.outfield(), key=lambda player: self.anchor_of(player)[0])

    def best_finisher(self) -> PlayerState:
        return max(self.outfield(), key=lambda player: player.player.traits.finishing)

    def anchor_of(self, player: PlayerState) -> Anchor:
        if player.slot is None:
            raise ValueError(f"{player.player_id} is not on the pitch")
        return self.anchors[player.slot]

    def substitute(self, player_in: PlayerState, player_out: PlayerState) -> None:
        player_in.slot, player_out.slot = player_out.slot, None
        player_in.has_played = True
