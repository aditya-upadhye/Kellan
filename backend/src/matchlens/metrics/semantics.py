from typing import Literal

from matchlens.models.base import TeamSide

ControlState = Literal["control", "balanced", "chaos"]


def momentum_side(value: float) -> TeamSide | None:
    if value == 0:
        return None
    return "home" if value > 0 else "away"


def control_state(value: float) -> ControlState:
    if value > 25:
        return "control"
    if value < -25:
        return "chaos"
    return "balanced"
