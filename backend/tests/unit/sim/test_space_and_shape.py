import pytest

from matchlens.models.base import TeamSide
from matchlens.sim.shape import opponent_defensive_line, team_shape
from matchlens.sim.space import (
    Period,
    Spot,
    attacks_right,
    from_attacking_frame,
    in_penalty_area,
    opponent,
    to_attacking_frame,
    to_point,
)
from matchlens.sim.squad import TeamState
from matchlens.world.meridian import KESTREL_BAY


@pytest.mark.parametrize(
    ("side", "period", "expected"),
    [("home", 1, True), ("home", 2, False), ("away", 1, False), ("away", 2, True)],
)
def test_attacking_direction_switches_at_half_time(
    side: TeamSide, period: Period, expected: bool
) -> None:
    assert attacks_right(side, period) is expected


def test_opponent_swaps_sides() -> None:
    assert (opponent("home"), opponent("away")) == ("away", "home")


@pytest.mark.parametrize("attacking_right", [True, False])
def test_attacking_frame_round_trips(attacking_right: bool) -> None:
    spot = Spot(20.0, 10.0)

    frame_spot = to_attacking_frame(spot, attacking_right=attacking_right)

    assert from_attacking_frame(frame_spot, attacking_right=attacking_right) == spot


def test_left_attackers_see_the_pitch_rotated() -> None:
    assert to_attacking_frame(Spot(20.0, 10.0), attacking_right=False) == Spot(85.0, 58.0)


@pytest.mark.parametrize(
    ("spot", "expected"),
    [(Spot(95.0, 34.0), True), (Spot(88.4, 34.0), False), (Spot(100.0, 13.0), False)],
)
def test_penalty_area_bounds(spot: Spot, expected: bool) -> None:
    assert in_penalty_area(spot) is expected


def test_points_are_clamped_and_rounded() -> None:
    point = to_point(Spot(105.04, -0.3))

    assert (point.x, point.y) == (105.0, 0.0)


def shape_in_frame(ball_depth: float, *, in_possession: bool) -> dict[str, Spot]:
    team = TeamState.from_team(KESTREL_BAY.as_team("home"))
    return team_shape(
        team, Spot(ball_depth, 34.0), attacking_right=True, in_possession=in_possession
    )


def test_goalkeeper_stays_deepest() -> None:
    shape = shape_in_frame(70.0, in_possession=True)

    assert min(shape.values(), key=lambda spot: spot.x) == shape["h01"]


def test_attackers_stay_onside_until_the_ball_passes_the_line() -> None:
    ball_depth = 60.0
    shape = shape_in_frame(ball_depth, in_possession=True)

    assert max(spot.x for spot in shape.values()) <= opponent_defensive_line(ball_depth)


def test_defending_block_is_more_compact_than_attacking_shape() -> None:
    def depth_spread(shape: dict[str, Spot]) -> float:
        outfield = [spot.x for player_id, spot in shape.items() if player_id != "h01"]
        return max(outfield) - min(outfield)

    assert depth_spread(shape_in_frame(52.5, in_possession=False)) < depth_spread(
        shape_in_frame(52.5, in_possession=True)
    )
