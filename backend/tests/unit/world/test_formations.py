import pytest

from matchlens.models.pitch import PITCH_LENGTH_M, PITCH_WIDTH_M
from matchlens.world.formations import FORMATION_ANCHORS, FORMATION_ROLES, formation_anchors


@pytest.mark.parametrize(("formation", "roles"), list(FORMATION_ROLES.items()))
def test_every_role_slot_has_an_anchor_on_the_pitch(formation: str, roles: tuple[str, ...]) -> None:
    anchors = formation_anchors(formation)

    assert len(anchors) == len(roles)
    assert all(
        0 < depth < PITCH_LENGTH_M and 0 < lateral < PITCH_WIDTH_M for depth, lateral in anchors
    )


def test_anchor_table_covers_exactly_the_known_formations() -> None:
    assert set(FORMATION_ANCHORS) == set(FORMATION_ROLES)


def test_unknown_formation_is_rejected() -> None:
    with pytest.raises(ValueError, match="no anchors defined for formation 3-5-2"):
        formation_anchors("3-5-2")
