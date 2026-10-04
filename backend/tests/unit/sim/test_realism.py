from statistics import mean

import pytest

from matchlens.config import get_settings
from matchlens.sim.match import simulate_scenario
from matchlens.sim.scenarios import load_scenario
from matchlens.world.meridian import MERIDIAN_LEAGUE
from support.match_stats import MatchSummary

REALISM_SEEDS = range(1, 51)
POSSESSION_BOUNDS_PCT = (35.0, 65.0)


pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def balanced_summaries() -> list[MatchSummary]:
    scenario = load_scenario("balanced", get_settings().scenarios_dir)
    return [
        MatchSummary.of(
            simulate_scenario(MERIDIAN_LEAGUE, scenario, seed, with_tracking=False).events
        )
        for seed in REALISM_SEEDS
    ]


@pytest.mark.parametrize(
    ("statistic", "low", "high"),
    [
        ("passes", 800, 1_100),
        ("pass_accuracy_pct", 75.0, 88.0),
        ("shots", 18, 32),
        ("goals", 2.0, 3.5),
        ("fouls", 15, 30),
        ("yellow_cards", 2, 6),
    ],
)
def test_balanced_scenario_averages_hit_the_realism_targets(
    balanced_summaries: list[MatchSummary], statistic: str, low: float, high: float
) -> None:
    average = mean(getattr(summary, statistic) for summary in balanced_summaries)

    assert low <= average <= high, f"{statistic} averaged {average:.2f}"


def test_every_balanced_match_splits_possession_within_bounds(
    balanced_summaries: list[MatchSummary],
) -> None:
    low, high = POSSESSION_BOUNDS_PCT

    assert all(low <= summary.home_possession_pct <= high for summary in balanced_summaries)
