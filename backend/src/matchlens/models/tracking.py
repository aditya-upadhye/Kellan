from pydantic import Field

from matchlens.models.base import Contract, Identifier, PlayerId
from matchlens.models.clock import MatchClock
from matchlens.models.pitch import PITCH_LENGTH_M, PITCH_WIDTH_M, Point


class PlayerPos(Contract):
    player_id: PlayerId
    x: float = Field(ge=0.0, le=PITCH_LENGTH_M)
    y: float = Field(ge=0.0, le=PITCH_WIDTH_M)
    speed_kmh: float = Field(ge=0.0)


class TrackingFrame(Contract):
    match_id: Identifier
    frame_seq: int = Field(ge=1)
    clock: MatchClock
    ball: Point
    ball_speed_kmh: float = Field(ge=0.0)
    players: list[PlayerPos]
