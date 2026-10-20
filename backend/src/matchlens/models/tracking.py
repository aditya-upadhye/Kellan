from typing import Literal

from pydantic import Field

from matchlens.models.base import Contract, Identifier, PlayerId
from matchlens.models.clock import MatchClock
from matchlens.models.pitch import PITCH_LENGTH_M, PITCH_WIDTH_M, Point


class PlayerPos(Contract):
    player_id: PlayerId
    x: float = Field(ge=0.0, le=PITCH_LENGTH_M)
    y: float = Field(ge=0.0, le=PITCH_WIDTH_M)
    speed_kmh: float = Field(ge=0.0)


class BallSample(Contract):
    """Authored synthetic ball movement within the preceding tracking second."""

    offset_ms: int = Field(ge=0, le=1_000)
    x: float = Field(ge=0.0, le=PITCH_LENGTH_M)
    y: float = Field(ge=0.0, le=PITCH_WIDTH_M)
    height_m: float = Field(ge=0.0, le=12.0)
    action: Literal["pass", "carry", "shot", "hold"] = "hold"
    actor_id: PlayerId | None = None
    event_id: str | None = None
    progress: float = Field(default=0.0, ge=0.0, le=1.0)


class TrackingFrame(Contract):
    match_id: Identifier
    frame_seq: int = Field(ge=1)
    clock: MatchClock
    ball: Point
    ball_speed_kmh: float = Field(ge=0.0)
    players: list[PlayerPos]
    ball_trajectory: list[BallSample] = Field(default_factory=list[BallSample])
