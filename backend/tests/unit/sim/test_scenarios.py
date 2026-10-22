# Scenario intent is exercised directly; outcomes still come from contacts.
# pyright: reportPrivateUsage=false
from pathlib import Path
from random import Random

import pytest
from pydantic import ValidationError

from matchlens.cli import main
from matchlens.config import get_settings
from matchlens.models.base import TeamSide
from matchlens.models.clock import MS_PER_MINUTE
from matchlens.models.events import CardEvent, GoalEvent, PressureEvent
from matchlens.sim.engine import MatchEngine
from matchlens.sim.match import (
    SimulatedMatch,
    build_scenario_metadata,
    simulate_scenario,
)
from matchlens.sim.output import EVENTS_FILE, FRAMES_FILE, METADATA_FILE
from matchlens.sim.scenarios import (
    Scenario,
    ScriptedAction,
    StyleShift,
    UnknownScenarioError,
    load_scenario,
    scenario_names,
    scenario_time_ms,
)
from matchlens.sim.space import Spot
from matchlens.sim.squad import PlayerState
from matchlens.world.meridian import MERIDIAN_LEAGUE

SCENARIOS_DIR = get_settings().scenarios_dir
INJECTION_TOLERANCE_MS = 90_000


def scenario(name: str) -> Scenario:
    return load_scenario(name, SCENARIOS_DIR)


def test_ships_the_three_spec_scenarios() -> None:
    assert scenario_names(SCENARIOS_DIR) == ["balanced", "late_comeback", "red_card_press"]


@pytest.mark.parametrize("name", ["balanced", "late_comeback", "red_card_press"])
def test_scenarios_reference_league_clubs(name: str) -> None:
    loaded = scenario(name)

    assert MERIDIAN_LEAGUE.club(loaded.home) != MERIDIAN_LEAGUE.club(loaded.away)


def test_parses_actions_and_style_shifts() -> None:
    loaded = scenario("late_comeback")
    shift = next(item for item in loaded.injections if isinstance(item, StyleShift))
    actions = [item for item in loaded.injections if isinstance(item, ScriptedAction)]

    assert shift.due_ms == 15 * MS_PER_MINUTE
    assert shift.changes_for("away") == {"possession": -0.2}
    assert [action.action for action in actions] == ["force_goal"] * 5


@pytest.mark.parametrize(
    ("value", "expected_ms"), [("0:00", 0), ("04:00", 240_000), ("43:30", 2_610_000)]
)
def test_converts_scenario_times(value: str, expected_ms: int) -> None:
    assert scenario_time_ms(value) == expected_ms


def write_scenario(directory: Path, name: str, body: str) -> None:
    (directory / f"{name}.yaml").write_text(body, encoding="utf-8")


BASE = "name: {name}\ndescription: Test.\nhome: kestrel-bay\naway: port-halden\n"


@pytest.mark.parametrize(
    ("injections", "reason"),
    [
        ('[{period: 2, at: "4:5", action: force_goal, team: home}]', "pattern"),
        ('[{period: 2, at: "45:00", action: force_goal, team: home}]', "before 45:00"),
        ('[{period: 3, at: "10:00", action: red_card, team: away}]', "period"),
        ('[{period: 2, at: "10:00", action: penalty, team: away}]', "action"),
        ('[{period: 2, from: "10:00", modify: {home.speed: 0.2}}]', "modify"),
        ('[{period: 2, from: "10:00", modify: {}}]', "modify"),
    ],
)
def test_rejects_invalid_injections(tmp_path: Path, injections: str, reason: str) -> None:
    write_scenario(tmp_path, "broken", BASE.format(name="broken") + f"injections: {injections}\n")

    with pytest.raises(ValidationError, match=reason):
        load_scenario("broken", tmp_path)


def test_rejects_a_club_playing_itself(tmp_path: Path) -> None:
    write_scenario(
        tmp_path, "mirror", BASE.format(name="mirror").replace("port-halden", "kestrel-bay")
    )

    with pytest.raises(ValidationError, match="cannot play itself"):
        load_scenario("mirror", tmp_path)


def test_rejects_a_file_whose_name_disagrees(tmp_path: Path) -> None:
    write_scenario(tmp_path, "derby", BASE.format(name="cup_final"))

    with pytest.raises(ValueError, match="declares name 'cup_final'"):
        load_scenario("derby", tmp_path)


def test_unknown_scenario_lists_what_exists() -> None:
    with pytest.raises(UnknownScenarioError, match="available: balanced, late_comeback"):
        load_scenario("friendly", SCENARIOS_DIR)


def test_style_overrides_shape_the_match_metadata() -> None:
    metadata = build_scenario_metadata(MERIDIAN_LEAGUE, scenario("late_comeback"), seed=1)

    assert metadata.match_id == "late_comeback-s1"
    assert metadata.home.style.directness == 0.3
    assert metadata.away.style.directness == 0.2
    assert metadata.away.style.press == MERIDIAN_LEAGUE.club("kestrel-bay").style.press


def test_scripted_attacks_activate_at_their_scheduled_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = scenario("late_comeback")
    engine = MatchEngine(
        build_scenario_metadata(MERIDIAN_LEAGUE, loaded, 1),
        Random(1),
        script=loaded.injections,
        record_tracking=False,
    )
    calls: list[tuple[int, int, TeamSide]] = []
    original = engine._start_forced_attack

    def activate(side: TeamSide) -> None:
        calls.append((engine._log.period, engine._log.ms, side))
        original(side)

    monkeypatch.setattr(engine, "_start_forced_attack", activate)
    actions = [item for item in loaded.injections if isinstance(item, ScriptedAction)]
    for action in actions:
        engine._log.start_period(action.period)
        engine._log.ms = action.due_ms
        engine._run_due_script()
    assert calls == [(action.period, action.due_ms, action.team) for action in actions]
    assert not any(isinstance(event, GoalEvent) for event in engine._log.events)


def test_scripted_attack_preserves_existing_possession_and_ball_state() -> None:
    engine = MatchEngine(
        build_scenario_metadata(MERIDIAN_LEAGUE, scenario("late_comeback"), 1),
        Random(1),
        record_tracking=False,
    )
    engine._possession = "away"
    engine._carrier = engine._teams["away"].outfield()[0]
    carrier, ball = engine._carrier, engine.world.ball
    engine._start_forced_attack("home")
    assert engine._forced_attack == "home"
    assert engine._possession == "away"
    assert engine._carrier == carrier
    assert engine.world.ball == ball
    assert not engine._log.events


@pytest.fixture(scope="module", params=[1, 2, 3])
def ten_men(request: pytest.FixtureRequest) -> SimulatedMatch:
    return simulate_scenario(
        MERIDIAN_LEAGUE, scenario("red_card_press"), request.param, with_tracking=False
    )


def test_scripted_red_card_is_shown_on_time(ten_men: SimulatedMatch) -> None:
    due_ms = 10 * MS_PER_MINUTE
    scripted = [
        event
        for event in ten_men.events
        if isinstance(event, CardEvent)
        and event.outcome == "red"
        and event.team_id == "away"
        and event.clock.period == 2
        and 0 <= event.clock.ms - due_ms <= INJECTION_TOLERANCE_MS
    ]

    assert len(scripted) == 1


def test_style_shift_raises_the_home_press(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = scenario("red_card_press")
    shift = next(item for item in loaded.injections if isinstance(item, StyleShift))

    def no_foul(_player: PlayerState, _chance: float) -> bool:
        return False

    counts: list[int] = []
    for shifted in (False, True):
        engine = MatchEngine(
            build_scenario_metadata(MERIDIAN_LEAGUE, loaded, 1), Random(42), record_tracking=False
        )
        engine.world.start_period(1)
        engine._possession = "away"
        engine._carrier = engine._teams["away"].outfield()[0]
        engine.world.place(Spot(70, 34))
        presser = engine._teams["home"].outfield()[0]
        engine.world.bodies[presser.player_id].spot = Spot(71, 34)
        monkeypatch.setattr(engine, "_commits_foul", no_foul)
        if shifted:
            engine._shift_style(shift)
        for _ in range(1000):
            engine._apply_defensive_pressure()
        counts.append(sum(isinstance(event, PressureEvent) for event in engine._log.events))
    assert counts[1] > counts[0] * 1.2


def test_cli_simulates_a_scenario(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        [
            "sim",
            "--scenario",
            "balanced",
            "--seed",
            "5",
            "--output-dir",
            str(tmp_path),
            "--events-only",
        ]
    )

    match_dir = tmp_path / "balanced-s5"
    assert exit_code == 0
    assert (match_dir / METADATA_FILE).is_file()
    assert (match_dir / EVENTS_FILE).is_file()
    assert not (match_dir / FRAMES_FILE).exists()
    assert "balanced-s5: Kestrel Bay Athletic" in capsys.readouterr().out


def test_cli_rejects_unknown_scenarios(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["sim", "--scenario", "friendly", "--seed", "1"]) == 2
    assert "no scenario 'friendly'" in capsys.readouterr().err
