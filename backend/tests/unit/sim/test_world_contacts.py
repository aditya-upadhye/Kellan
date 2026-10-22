# These focused physics regressions intentionally exercise internal solvers.
# pyright: reportPrivateUsage=false
import math
from random import Random

import pytest

from matchlens.config import get_settings
from matchlens.models.events import PassEvent
from matchlens.sim.engine import MatchEngine
from matchlens.sim.match import build_scenario_metadata
from matchlens.sim.scenarios import load_scenario
from matchlens.sim.space import Spot
from matchlens.sim.world import BODY_GAP, Body, Contact, Flight
from matchlens.world.meridian import MERIDIAN_LEAGUE


@pytest.fixture
def engine() -> MatchEngine:
    scenario = load_scenario("balanced", get_settings().scenarios_dir)
    metadata = build_scenario_metadata(MERIDIAN_LEAGUE, scenario, 1)
    result = MatchEngine(metadata, Random(1), record_tracking=False)
    result.world.start_period(1)
    return result


def body(x: float, y: float, vx: float = 0.0) -> Body:
    return Body(Spot(x, y), Spot(vx, 0.0), math.pi / 2)


def flight(actor: str = "h01") -> Flight:
    return Flight(actor, "home", "h02", "pass", Spot(10, 10), Spot(30, 10), 30, Spot(30, 0), 0, 0)


@pytest.mark.parametrize("player_id", ["h03", "a03", "h01"])
def test_ball_hits_every_body_including_teammates_and_the_kicker(
    engine: MatchEngine, player_id: str
) -> None:
    world = engine.world
    world.bodies = {player_id: body(20, 10)}
    world.flight = flight()
    hits = world._contacts(Spot(10, 10), Spot(30, 10), 0, 0, {player_id: Spot(20, 10)})
    assert hits
    fraction, contacted = min(hits)
    assert contacted == player_id
    assert 0 < fraction < 0.5


def test_airborne_ball_clears_body_but_descending_ball_hits_it(engine: MatchEngine) -> None:
    world = engine.world
    world.bodies = {"a03": body(20, 10)}
    world.flight = flight()
    previous = {"a03": Spot(20, 10)}
    assert not world._contacts(Spot(10, 10), Spot(30, 10), 3, 3, previous)
    assert world._contacts(Spot(10, 10), Spot(30, 10), 3, 0, previous)


def test_swept_players_cannot_exchange_sides_through_each_other(engine: MatchEngine) -> None:
    world = engine.world
    world.bodies = {"h03": body(10, 10, 20), "a03": body(12, 10, -20)}
    world.ball = Spot(60, 40)
    world._advance_bodies(0.1)
    left, right = world.bodies["h03"], world.bodies["a03"]
    assert left.spot.x < right.spot.x
    assert left.spot.distance_to(right.spot) >= BODY_GAP - 1e-6
    assert left.velocity.x <= right.velocity.x + 1e-6


def test_overlap_repair_is_not_limited_to_a_gentle_nudge(engine: MatchEngine) -> None:
    world = engine.world
    world.bodies = {"h03": body(10, 10), "a03": body(10, 10)}
    world._separate(0.05)
    assert world.bodies["h03"].spot.distance_to(world.bodies["a03"].spot) >= BODY_GAP - 1e-6


def test_controlled_ball_stops_at_another_body(engine: MatchEngine) -> None:
    world = engine.world
    world.bodies = {"h03": body(11, 10), "a03": body(12, 10)}
    previous = {"h03": Spot(10, 10), "a03": Spot(12, 10)}
    world._body_steps = [
        (0, previous),
        (1, {key: value.spot for key, value in world.bodies.items()}),
    ]
    world.owner_id = "h03"
    world.controlled = True
    world.ball = Spot(10.764, 10)
    world._control_ball(0.2, previous)
    assert all(world.ball.distance_to(player.spot) >= 0.68 for player in world.bodies.values())


def test_blocked_kick_recovered_by_passer_is_not_a_self_pass(
    engine: MatchEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    passer = engine._carrier
    receiver = next(player for player in engine._teams["home"].outfield() if player != passer)

    def prepared(_target: Spot | None = None) -> bool:
        return True

    monkeypatch.setattr(engine, "_prepare_control", prepared)
    monkeypatch.setattr(
        engine, "_run_flight", lambda: Contact("complete", Spot(52.5, 34), passer.player_id)
    )
    assert not engine._deliver_pass(receiver, Spot(60, 34), height="ground")
    event = engine._log.events[-1]
    assert isinstance(event, PassEvent)
    assert event.outcome == "incomplete"
    assert event.attrs.receiver_id != event.player_id
    assert engine._carrier == passer


def test_carrier_walks_around_stationary_ball_to_prepare_a_kick(engine: MatchEngine) -> None:
    world = engine.world
    carrier = world.bodies[engine._carrier.player_id]
    for index, (key, player) in enumerate(world.bodies.items()):
        if key != engine._carrier.player_id:
            player.spot = Spot(70 + index % 5 * 2, 30 + index // 5 * 3)
    world.place(Spot(20, 10))
    carrier.spot, carrier.velocity, carrier.heading = Spot(21, 10), Spot(0, 0), math.pi / 2
    engine._prepare_control(Spot(30, 10))
    assert world.ready(Spot(30, 10))
    assert engine._log.ms < 5000


def test_reported_speed_uses_resolved_displacement_not_requested_velocity(
    engine: MatchEngine,
) -> None:
    world = engine.world
    world.record = True
    world.bodies = {"h03": body(20, 10, 8)}
    world._record_initial()
    world.ms = 100
    world._write_frame()
    assert world.frames[-1].players[0].speed_kmh == 0


def test_failed_control_prevents_a_kick(
    engine: MatchEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    receiver = next(
        player for player in engine._teams["home"].outfield() if player != engine._carrier
    )

    def not_ready(_target: Spot | None = None) -> bool:
        return False

    monkeypatch.setattr(engine, "_prepare_control", not_ready)
    assert not engine._deliver_pass(receiver, Spot(70, 34), height="ground")
    assert not engine._log.events
    assert engine.world.flight is None


def test_control_handover_does_not_move_ball_back_to_old_contact(engine: MatchEngine) -> None:
    engine.world.ball = Spot(55, 34)
    engine.world.control_contact = Contact("intercepted", Spot(50, 34), "a03")
    assert engine._resolve_control_contact()
    assert engine.world.ball == Spot(55, 34)
    assert engine._possession == "away"
    assert engine._carrier.player_id == "a03"


def test_first_touch_at_touchline_does_not_require_an_off_pitch_foot(engine: MatchEngine) -> None:
    world = engine.world
    carrier = world.bodies[engine._carrier.player_id]
    for index, (key, player) in enumerate(world.bodies.items()):
        if key != engine._carrier.player_id:
            player.spot = Spot(70 + index % 5 * 2, 30 + index // 5 * 3)
    world.place(Spot(0, 10))
    carrier.spot, carrier.velocity, carrier.heading = Spot(0, 10.8), Spot(0, 0), -math.pi / 2
    assert engine._prepare_control(Spot(20, 10))
    assert engine._log.ms < 5000
    assert carrier.spot.distance_to(world.ball) >= 0.684


def test_contact_against_wall_does_not_freeze_unrelated_players(engine: MatchEngine) -> None:
    world = engine.world
    world.ball = Spot(60, 40)
    world.bodies = {
        "h03": body(0, 10, -1),
        "a03": body(BODY_GAP, 10, -3),
        "h04": body(30, 20, 4),
    }
    world._advance_bodies(0.1)
    assert world.bodies["h04"].spot.x == pytest.approx(30.4)
    assert world.bodies["h03"].spot.distance_to(world.bodies["a03"].spot) >= BODY_GAP - 1e-6


def test_mid_match_kickoff_players_retreat_around_the_stationary_ball(engine: MatchEngine) -> None:
    world = engine.world
    engine._log.start_period(2)
    engine._log.ms = 1000
    world.start_period(2)
    world.ms = 1000
    engine._carrier = engine._teams["home"].player("h09")
    world.bodies["h09"].spot = Spot(50.8831997, 33.9880389)
    world.bodies["a10"].spot = Spot(53.1838011, 33.9835057)
    world.bodies["a09"].spot = Spot(54.0443521, 34.0606289)
    world.kickoff("h09", "home")
    assert engine._prepare_control()
    assert engine._log.ms < 16_000
    assert all(
        world.bodies[player.player_id].spot.distance_to(world.ball) >= 9
        for player in engine._teams["away"].on_pitch()
    )
