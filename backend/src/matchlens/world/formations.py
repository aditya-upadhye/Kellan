from typing import Literal

from matchlens.models.match import Position, Role

Formation = Literal["4-3-3", "4-2-3-1", "4-4-2", "4-1-4-1"]

FORMATION_ROLES: dict[Formation, tuple[Role, ...]] = {
    "4-3-3": ("GK", "FB", "CB", "CB", "FB", "DM", "CM", "CM", "W", "ST", "W"),
    "4-2-3-1": ("GK", "FB", "CB", "CB", "FB", "DM", "CM", "W", "AM", "W", "ST"),
    "4-4-2": ("GK", "FB", "CB", "CB", "FB", "W", "CM", "CM", "W", "ST", "ST"),
    "4-1-4-1": ("GK", "FB", "CB", "CB", "FB", "DM", "W", "CM", "CM", "W", "ST"),
}

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
