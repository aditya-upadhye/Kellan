import pytest

from matchlens.metrics.xg import PENALTY_XG, expected_goals, shot_geometry
from matchlens.models.pitch import Point


def open_play_xg(x: float, y: float, *, attacking_right: bool = True) -> float:
    geometry = shot_geometry(Point(x=x, y=y), attacking_right=attacking_right)
    return expected_goals(geometry, "foot", "open_play")


@pytest.mark.parametrize(
    ("distance_m", "low", "high"),
    [(6.0, 0.35, 0.55), (11.0, 0.15, 0.3), (18.0, 0.05, 0.12), (25.0, 0.02, 0.06)],
)
def test_central_shots_have_reference_values(distance_m: float, low: float, high: float) -> None:
    assert low <= open_play_xg(105.0 - distance_m, 34.0) <= high


def test_closer_shots_score_higher() -> None:
    values = [open_play_xg(105.0 - distance, 34.0) for distance in (30, 22, 16, 11, 6, 3)]

    assert values == sorted(values)


def test_more_central_shots_score_higher() -> None:
    values = [open_play_xg(94.0, lateral) for lateral in (4.0, 12.0, 20.0, 28.0, 34.0)]

    assert values == sorted(values)


def test_headers_score_lower_than_shots_with_the_foot() -> None:
    geometry = shot_geometry(Point(x=97.0, y=34.0), attacking_right=True)

    assert expected_goals(geometry, "head", "open_play") < expected_goals(
        geometry, "foot", "open_play"
    )


def test_penalties_use_the_fixed_value() -> None:
    geometry = shot_geometry(Point(x=94.0, y=34.0), attacking_right=True)

    assert expected_goals(geometry, "foot", "penalty") == PENALTY_XG


def test_geometry_mirrors_for_teams_attacking_left() -> None:
    assert open_play_xg(12.0, 30.0, attacking_right=False) == pytest.approx(
        open_play_xg(93.0, 38.0)
    )
