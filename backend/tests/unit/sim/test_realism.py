import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from statistics import mean

import pytest

from support.match_stats import MatchSummary, balanced_summary

# PR CI can choose a small, deterministic sample while the scheduled workflow
# runs the full 50-seed sweep. Local runs keep the full sweep by default.
REALISM_SEED_COUNT = int(os.environ.get("KELLAN_REALISM_SEED_COUNT", "50"))
if REALISM_SEED_COUNT < 1:
    raise ValueError("KELLAN_REALISM_SEED_COUNT must be at least 1")
REALISM_SEEDS = range(1, REALISM_SEED_COUNT + 1)
POSSESSION_BOUNDS_PCT = (35.0, 65.0)


pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def balanced_summaries() -> list[MatchSummary]:
    # Each fixture is independent, so bounded workers avoid serializing the
    # expensive physics without oversubscribing standard GitHub-hosted runners.
    with ProcessPoolExecutor(max_workers=min(4, os.cpu_count() or 1)) as pool:
        futures = {pool.submit(balanced_summary, seed): seed for seed in REALISM_SEEDS}
        summaries: dict[int, MatchSummary] = {}
        for future in as_completed(futures):
            seed = futures[future]
            summaries[seed] = future.result()
            print(f"seed={seed} {asdict(summaries[seed])}", flush=True)
        return [summaries[seed] for seed in REALISM_SEEDS]


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

    outliers = [
        (seed, asdict(summary))
        for seed, summary in zip(REALISM_SEEDS, balanced_summaries, strict=True)
        if not low <= summary.home_possession_pct <= high
    ]
    assert not outliers, outliers
