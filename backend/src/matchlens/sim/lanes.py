"""Geometric lane checks for the synthetic match's planned player positions."""

import math
from collections.abc import Mapping
from dataclasses import dataclass

from matchlens.sim.space import Spot


@dataclass(frozen=True, slots=True)
class LaneContact:
    player_id: str
    spot: Spot
    progress: float


def pass_apex(length: float, height: str) -> float:
    if height == "high":
        return min(7.0, 1.4 + length * 0.1)
    return 0.45 if height == "low" else 0.0


def lane_contacts(
    origin: Spot, target: Spot, defenders: Mapping[str, Spot], *, apex_m: float = 0.0
) -> list[LaneContact]:
    """Find reachable contacts in order along the route, excluding endpoints.

    A player can reach a ground ball within 1.05 m. Airborne reach narrows
    toward head height; high balls may legitimately clear the same player.
    This is a planned-position approximation, not rigid-body collision physics.
    """
    dx, dy = target.x - origin.x, target.y - origin.y
    length_squared = dx * dx + dy * dy
    if length_squared < 0.01:
        return []
    contacts: list[LaneContact] = []
    for player_id, defender in defenders.items():
        progress = ((defender.x - origin.x) * dx + (defender.y - origin.y) * dy) / length_squared
        if not 0.025 < progress < 0.98:
            continue
        spot = origin.toward(target, progress)
        height = 4 * apex_m * progress * (1 - progress)
        if height > 2.1:
            continue
        reach = 1.05 if height <= 0.6 else 0.65
        if math.hypot(defender.x - spot.x, defender.y - spot.y) <= reach:
            contacts.append(LaneContact(player_id, spot, progress))
    return sorted(contacts, key=lambda contact: contact.progress)
