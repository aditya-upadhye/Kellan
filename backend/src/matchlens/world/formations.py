from typing import Literal

from matchlens.models.match import Position, Role

Formation = Literal["4-3-3", "4-2-3-1", "4-4-2", "4-1-4-1"]

FORMATION_ROLES: dict[Formation, tuple[Role, ...]] = {
    "4-3-3": ("GK", "FB", "CB", "CB", "FB", "DM", "CM", "CM", "W", "ST", "W"),
    "4-2-3-1": ("GK", "FB", "CB", "CB", "FB", "DM", "CM", "W", "AM", "W", "ST"),
    "4-4-2": ("GK", "FB", "CB", "CB", "FB", "W", "CM", "CM", "W", "ST", "ST"),
    "4-1-4-1": ("GK", "FB", "CB", "CB", "FB", "DM", "W", "CM", "CM", "W", "ST"),
}

Anchor = tuple[float, float]

BACK_FOUR: tuple[Anchor, ...] = ((6.0, 34.0), (40.0, 60.0), (30.0, 44.0), (30.0, 24.0), (40.0, 8.0))

FORMATION_ANCHORS: dict[str, tuple[Anchor, ...]] = {
    "4-3-3": (
        *BACK_FOUR,
        (45.0, 34.0),
        (56.0, 48.0),
        (56.0, 20.0),
        (72.0, 60.0),
        (79.0, 34.0),
        (72.0, 8.0),
    ),
    "4-2-3-1": (
        *BACK_FOUR,
        (45.0, 42.0),
        (47.0, 26.0),
        (68.0, 60.0),
        (65.0, 34.0),
        (68.0, 8.0),
        (79.0, 34.0),
    ),
    "4-4-2": (
        *BACK_FOUR,
        (60.0, 60.0),
        (51.0, 42.0),
        (51.0, 26.0),
        (60.0, 8.0),
        (77.0, 42.0),
        (77.0, 26.0),
    ),
    "4-1-4-1": (
        *BACK_FOUR,
        (43.0, 34.0),
        (63.0, 60.0),
        (55.0, 45.0),
        (55.0, 23.0),
        (63.0, 8.0),
        (79.0, 34.0),
    ),
}


def formation_anchors(formation: str) -> tuple[Anchor, ...]:
    if formation not in FORMATION_ANCHORS:
        raise ValueError(f"no anchors defined for formation {formation}")
    return FORMATION_ANCHORS[formation]


POSITION_BY_ROLE: dict[Role, Position] = {
    "GK": "GK",
    "CB": "DF",
    "FB": "DF",
    "DM": "MF",
    "CM": "MF",
    "AM": "MF",
    "W": "FW",
    "ST": "FW",
}
