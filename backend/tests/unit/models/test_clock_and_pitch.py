import pytest
from pydantic import ValidationError

from matchlens.models.clock import MatchClock
from matchlens.models.pitch import PITCH_LENGTH_M, PITCH_WIDTH_M, Point


@pytest.mark.parametrize(
    ("period", "ms", "expected"),
    [
        (1, 0, "1'"),
        (1, 22 * 60_000 + 30_000, "23'"),
        (1, 45 * 60_000 - 1, "45'"),
        (1, 45 * 60_000, "45+1'"),
        (1, 47 * 60_000 + 5, "45+3'"),
        (2, 0, "46'"),
        (2, 45 * 60_000 - 1, "90'"),
        (2, 46 * 60_000, "90+2'"),
    ],
)
def test_clock_displays_broadcast_minute(period: int, ms: int, expected: str) -> None:
    clock = MatchClock.model_validate({"period": period, "ms": ms})

    assert clock.display == expected


@pytest.mark.parametrize("payload", [{"period": 3, "ms": 0}, {"period": 1, "ms": -1}])
def test_clock_rejects_invalid_values(payload: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        MatchClock.model_validate(payload)


def test_point_accepts_pitch_corners() -> None:
    far_corner = Point(x=PITCH_LENGTH_M, y=PITCH_WIDTH_M)

    assert (far_corner.x, far_corner.y) == (105.0, 68.0)
    assert Point(x=0.0, y=0.0).x == 0.0


@pytest.mark.parametrize(("x", "y"), [(-0.1, 10.0), (105.1, 10.0), (50.0, -0.1), (50.0, 68.1)])
def test_point_rejects_coordinates_off_the_pitch(x: float, y: float) -> None:
    with pytest.raises(ValidationError):
        Point(x=x, y=y)


def test_contracts_are_immutable() -> None:
    point = Point(x=10.0, y=10.0)

    with pytest.raises(ValidationError):
        point.x = 20.0
