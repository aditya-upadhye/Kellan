import math
from typing import Literal, NamedTuple

from matchlens.models.base import TeamSide
from matchlens.models.pitch import PITCH_LENGTH_M, PITCH_WIDTH_M, Point

Period = Literal[1, 2]

HALFWAY_M = PITCH_LENGTH_M / 2
CENTRE_LATERAL_M = PITCH_WIDTH_M / 2
PENALTY_AREA_DEPTH_M = 16.5
PENALTY_AREA_HALF_WIDTH_M = 20.16
PENALTY_SPOT_DISTANCE_M = 11.0


class Spot(NamedTuple):
    x: float
    y: float

    def distance_to(self, other: "Spot") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def toward(self, other: "Spot", fraction: float) -> "Spot":
        return Spot(self.x + (other.x - self.x) * fraction, self.y + (other.y - self.y) * fraction)


CENTRE_SPOT = Spot(HALFWAY_M, CENTRE_LATERAL_M)


def opponent(side: TeamSide) -> TeamSide:
    return "away" if side == "home" else "home"


def attacks_right(side: TeamSide, period: Period) -> bool:
    return (side == "home") == (period == 1)


def to_attacking_frame(spot: Spot, *, attacking_right: bool) -> Spot:
    if attacking_right:
        return spot
    return Spot(PITCH_LENGTH_M - spot.x, PITCH_WIDTH_M - spot.y)


def from_attacking_frame(spot: Spot, *, attacking_right: bool) -> Spot:
    return to_attacking_frame(spot, attacking_right=attacking_right)


def clamp_to_pitch(spot: Spot) -> Spot:
    return Spot(min(max(spot.x, 0.0), PITCH_LENGTH_M), min(max(spot.y, 0.0), PITCH_WIDTH_M))


def in_penalty_area(frame_spot: Spot) -> bool:
    return (
        frame_spot.x >= PITCH_LENGTH_M - PENALTY_AREA_DEPTH_M
        and abs(frame_spot.y - CENTRE_LATERAL_M) <= PENALTY_AREA_HALF_WIDTH_M
    )


def to_point(spot: Spot) -> Point:
    clamped = clamp_to_pitch(spot)
    return Point(x=round(clamped.x, 1), y=round(clamped.y, 1))
