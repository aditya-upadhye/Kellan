import filecmp
import os
import subprocess
import sys
from pathlib import Path

import pytest

from matchlens.config import get_settings
from matchlens.sim.match import simulate_scenario
from matchlens.sim.output import EVENTS_FILE, FRAMES_FILE, METADATA_FILE, write_match
from matchlens.sim.scenarios import load_scenario
from matchlens.world.meridian import MERIDIAN_LEAGUE

MATCH_FILES = (METADATA_FILE, EVENTS_FILE, FRAMES_FILE)


def identical(first: Path, second: Path, names: tuple[str, ...]) -> bool:
    return all(filecmp.cmp(first / name, second / name, shallow=False) for name in names)


def run_sim_cli(output_dir: Path, *options: str, hash_seed: str = "0") -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "matchlens.cli", "sim", "--output-dir", str(output_dir), *options],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ | {"PYTHONHASHSEED": hash_seed},
    )
    return completed.stdout


@pytest.mark.slow
def test_same_seed_and_scenario_write_byte_identical_files(tmp_path: Path) -> None:
    scenario = load_scenario("late_comeback", get_settings().scenarios_dir)

    first = write_match(simulate_scenario(MERIDIAN_LEAGUE, scenario, 11), tmp_path / "first")
    second = write_match(simulate_scenario(MERIDIAN_LEAGUE, scenario, 11), tmp_path / "second")

    assert identical(first, second, MATCH_FILES)


def test_output_does_not_depend_on_the_process_hash_seed(tmp_path: Path) -> None:
    options = ("--scenario", "red_card_press", "--seed", "7", "--events-only")

    run_sim_cli(tmp_path / "first", *options, hash_seed="1")
    run_sim_cli(tmp_path / "second", *options, hash_seed="2")

    assert identical(
        tmp_path / "first" / "red_card_press-s7",
        tmp_path / "second" / "red_card_press-s7",
        (METADATA_FILE, EVENTS_FILE),
    )


def test_different_seeds_play_different_matches() -> None:
    scenario = load_scenario("balanced", get_settings().scenarios_dir)

    first = simulate_scenario(MERIDIAN_LEAGUE, scenario, 1, with_tracking=False)
    second = simulate_scenario(MERIDIAN_LEAGUE, scenario, 2, with_tracking=False)

    assert first.events != second.events


# Live startup is measured in test_stream: first input within five seconds.
# The offline CLI still computes the complete fixture and reports its duration.
