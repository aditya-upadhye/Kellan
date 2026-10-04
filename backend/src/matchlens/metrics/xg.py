import math
from dataclasses import dataclass

from matchlens.models.events import BodyPart, ShotSituation
from matchlens.models.pitch import PITCH_LENGTH_M, PITCH_WIDTH_M, Point

GOAL_WIDTH_M = 7.32
PENALTY_XG = 0.76
INTERCEPT = -0.59
ANGLE_WEIGHT = 1.02
DISTANCE_WEIGHT = -0.121
HEADER_PENALTY = 0.9


@dataclass(frozen=True, slots=True)
class ShotGeometry:
    distance_m: float
    angle_rad: float


def shot_geometry(location: Point, *, attacking_right: bool) -> ShotGeometry:
    goal_line_x = PITCH_LENGTH_M if attacking_right else 0.0
    depth = abs(goal_line_x - location.x)
    offset = abs(location.y - PITCH_WIDTH_M / 2)
    distance = math.hypot(depth, offset)
    visible_angle = math.atan2(GOAL_WIDTH_M * depth, depth**2 + offset**2 - (GOAL_WIDTH_M / 2) ** 2)
    return ShotGeometry(distance_m=distance, angle_rad=visible_angle)


def logit(probability: float) -> float:
    return math.log(probability / (1.0 - probability))


def sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def expected_goals(geometry: ShotGeometry, body_part: BodyPart, situation: ShotSituation) -> float:
    if situation == "penalty":
        return PENALTY_XG
    score = INTERCEPT + ANGLE_WEIGHT * geometry.angle_rad + DISTANCE_WEIGHT * geometry.distance_m
    if body_part == "head":
        score -= HEADER_PENALTY
    return sigmoid(score)
