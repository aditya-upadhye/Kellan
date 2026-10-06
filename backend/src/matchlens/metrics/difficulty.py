import math

from matchlens.models.events import PassEvent
from matchlens.models.pitch import PITCH_LENGTH_M


def pass_difficulty(event: PassEvent) -> float:
    """A 0-100 difficulty score, increasing with distance and pressure."""
    forward = (event.end_location.x - event.location.x) * (
        1 if (event.team_id == "home") == (event.clock.period == 1) else -1
    )
    target_progress = (
        event.end_location.x
        if (event.team_id == "home") == (event.clock.period == 1)
        else PITCH_LENGTH_M - event.end_location.x
    )
    score = (
        -2.2
        + 0.055 * event.attrs.length_m
        + 0.85 * event.attrs.under_pressure
        + {"ground": 0.0, "low": 0.25, "high": 0.55}[event.attrs.height]
        + 0.014 * max(0.0, forward)
        + 0.4 * (target_progress >= 70)
    )
    return 100 / (1 + math.exp(-score))
