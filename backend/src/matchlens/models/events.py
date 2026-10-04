from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, model_validator

from matchlens.models.base import Contract, Identifier, PlayerId, TeamSide
from matchlens.models.clock import MatchClock
from matchlens.models.pitch import Point


class EventType(StrEnum):
    KICKOFF = "kickoff"
    PASS = "pass"
    CARRY = "carry"
    SHOT = "shot"
    TACKLE = "tackle"
    INTERCEPTION = "interception"
    PRESSURE = "pressure"
    DUEL = "duel"
    FOUL = "foul"
    CARD = "card"
    SUBSTITUTION = "substitution"
    GOAL = "goal"
    POSSESSION_CHANGE = "possession_change"
    BALL_OUT = "ball_out"
    PERIOD_END = "period_end"
    MATCH_END = "match_end"


PassOutcome = Literal["complete", "incomplete", "out", "offside"]
ShotOutcome = Literal["goal", "saved", "blocked", "off_target", "woodwork"]
DuelOutcome = Literal["won", "lost"]
CardOutcome = Literal["yellow", "second_yellow", "red"]
PassHeight = Literal["ground", "low", "high"]
BodyPart = Literal["foot", "head"]
ShotSituation = Literal["open_play", "set_piece", "penalty"]
Speed = Annotated[float, Field(ge=0.0)]
Distance = Annotated[float, Field(ge=0.0)]


def format_event_id(match_id: str, seq: int) -> str:
    return f"{match_id}-{seq:06d}"


class NoAttrs(Contract):
    pass


class PassAttrs(Contract):
    receiver_id: PlayerId
    length_m: Distance
    height: PassHeight
    under_pressure: bool
    ball_speed_kmh: Speed


class CarryAttrs(Contract):
    distance_m: Distance


class ShotAttrs(Contract):
    body_part: BodyPart
    shot_speed_kmh: Speed
    situation: ShotSituation
    assist_event_id: str | None


class DuelAttrs(Contract):
    opponent_id: PlayerId


class PressureAttrs(Contract):
    target_player_id: PlayerId


class FoulAttrs(Contract):
    fouled_player_id: PlayerId


class CardAttrs(Contract):
    reason: str = Field(min_length=1, max_length=40)


class SubstitutionAttrs(Contract):
    player_in_id: PlayerId
    player_out_id: PlayerId


class GoalAttrs(Contract):
    scorer_id: PlayerId
    assist_id: PlayerId | None
    shot_event_id: str


class BaseEvent(Contract):
    event_id: str
    match_id: Identifier
    seq: int = Field(ge=1)
    clock: MatchClock

    @model_validator(mode="after")
    def event_id_matches_match_and_seq(self) -> Self:
        expected_id = format_event_id(self.match_id, self.seq)
        if self.event_id != expected_id:
            raise ValueError(f"event_id must be {expected_id}")
        return self


class KickoffEvent(BaseEvent):
    type: Literal[EventType.KICKOFF] = EventType.KICKOFF
    team_id: TeamSide
    player_id: PlayerId
    location: Point
    end_location: None = None
    outcome: None = None
    attrs: NoAttrs = NoAttrs()


class PassEvent(BaseEvent):
    type: Literal[EventType.PASS] = EventType.PASS
    team_id: TeamSide
    player_id: PlayerId
    location: Point
    end_location: Point
    outcome: PassOutcome
    attrs: PassAttrs

    @model_validator(mode="after")
    def passer_is_not_receiver(self) -> Self:
        if self.attrs.receiver_id == self.player_id:
            raise ValueError("a player cannot pass to themselves")
        return self


class CarryEvent(BaseEvent):
    type: Literal[EventType.CARRY] = EventType.CARRY
    team_id: TeamSide
    player_id: PlayerId
    location: Point
    end_location: Point
    outcome: None = None
    attrs: CarryAttrs


class ShotEvent(BaseEvent):
    type: Literal[EventType.SHOT] = EventType.SHOT
    team_id: TeamSide
    player_id: PlayerId
    location: Point
    end_location: Point | None = None
    outcome: ShotOutcome
    attrs: ShotAttrs


class TackleEvent(BaseEvent):
    type: Literal[EventType.TACKLE] = EventType.TACKLE
    team_id: TeamSide
    player_id: PlayerId
    location: Point
    end_location: None = None
    outcome: DuelOutcome
    attrs: DuelAttrs


class InterceptionEvent(BaseEvent):
    type: Literal[EventType.INTERCEPTION] = EventType.INTERCEPTION
    team_id: TeamSide
    player_id: PlayerId
    location: Point
    end_location: None = None
    outcome: None = None
    attrs: NoAttrs = NoAttrs()


class PressureEvent(BaseEvent):
    type: Literal[EventType.PRESSURE] = EventType.PRESSURE
    team_id: TeamSide
    player_id: PlayerId
    location: Point
    end_location: None = None
    outcome: None = None
    attrs: PressureAttrs


class DuelEvent(BaseEvent):
    type: Literal[EventType.DUEL] = EventType.DUEL
    team_id: TeamSide
    player_id: PlayerId
    location: Point
    end_location: None = None
    outcome: DuelOutcome
    attrs: DuelAttrs


class FoulEvent(BaseEvent):
    type: Literal[EventType.FOUL] = EventType.FOUL
    team_id: TeamSide
    player_id: PlayerId
    location: Point
    end_location: None = None
    outcome: None = None
    attrs: FoulAttrs


class CardEvent(BaseEvent):
    type: Literal[EventType.CARD] = EventType.CARD
    team_id: TeamSide
    player_id: PlayerId
    location: None = None
    end_location: None = None
    outcome: CardOutcome
    attrs: CardAttrs


class SubstitutionEvent(BaseEvent):
    type: Literal[EventType.SUBSTITUTION] = EventType.SUBSTITUTION
    team_id: TeamSide
    player_id: None = None
    location: None = None
    end_location: None = None
    outcome: None = None
    attrs: SubstitutionAttrs

    @model_validator(mode="after")
    def players_belong_to_substituting_team(self) -> Self:
        side_prefix = self.team_id[0]
        swapped_ids = (self.attrs.player_in_id, self.attrs.player_out_id)
        if self.attrs.player_in_id == self.attrs.player_out_id:
            raise ValueError("player_in_id and player_out_id must differ")
        if any(not player_id.startswith(side_prefix) for player_id in swapped_ids):
            raise ValueError(f"substituted players must belong to {self.team_id}")
        return self


class GoalEvent(BaseEvent):
    type: Literal[EventType.GOAL] = EventType.GOAL
    team_id: TeamSide
    player_id: PlayerId
    location: None = None
    end_location: None = None
    outcome: None = None
    attrs: GoalAttrs

    @model_validator(mode="after")
    def scorer_is_event_player(self) -> Self:
        if self.attrs.scorer_id != self.player_id:
            raise ValueError("scorer_id must equal player_id")
        return self


class PossessionChangeEvent(BaseEvent):
    type: Literal[EventType.POSSESSION_CHANGE] = EventType.POSSESSION_CHANGE
    team_id: TeamSide
    player_id: None = None
    location: None = None
    end_location: None = None
    outcome: None = None
    attrs: NoAttrs = NoAttrs()


class BallOutEvent(BaseEvent):
    type: Literal[EventType.BALL_OUT] = EventType.BALL_OUT
    team_id: TeamSide | None = None
    player_id: PlayerId | None = None
    location: Point
    end_location: None = None
    outcome: None = None
    attrs: NoAttrs = NoAttrs()


class PeriodEndEvent(BaseEvent):
    type: Literal[EventType.PERIOD_END] = EventType.PERIOD_END
    team_id: None = None
    player_id: None = None
    location: None = None
    end_location: None = None
    outcome: None = None
    attrs: NoAttrs = NoAttrs()


class MatchEndEvent(BaseEvent):
    type: Literal[EventType.MATCH_END] = EventType.MATCH_END
    team_id: None = None
    player_id: None = None
    location: None = None
    end_location: None = None
    outcome: None = None
    attrs: NoAttrs = NoAttrs()


MatchEvent = Annotated[
    KickoffEvent
    | PassEvent
    | CarryEvent
    | ShotEvent
    | TackleEvent
    | InterceptionEvent
    | PressureEvent
    | DuelEvent
    | FoulEvent
    | CardEvent
    | SubstitutionEvent
    | GoalEvent
    | PossessionChangeEvent
    | BallOutEvent
    | PeriodEndEvent
    | MatchEndEvent,
    Field(discriminator="type"),
]

MATCH_EVENT_ADAPTER: TypeAdapter[MatchEvent] = TypeAdapter(MatchEvent)
