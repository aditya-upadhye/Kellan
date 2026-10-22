import math
from collections.abc import Callable, Sequence
from random import Random
from typing import Literal

from matchlens.metrics.xg import expected_goals, logit, shot_geometry, sigmoid
from matchlens.models.base import TeamSide
from matchlens.models.clock import MS_PER_MINUTE, REGULATION_PERIOD_MINUTES
from matchlens.models.events import (
    BallOutEvent,
    BaseEvent,
    BodyPart,
    CardAttrs,
    CardEvent,
    CardOutcome,
    CarryAttrs,
    CarryEvent,
    DuelAttrs,
    DuelEvent,
    FoulAttrs,
    FoulEvent,
    GoalAttrs,
    GoalEvent,
    InterceptionEvent,
    KickoffEvent,
    MatchEndEvent,
    MatchEvent,
    PassAttrs,
    PassEvent,
    PassHeight,
    PassOutcome,
    PeriodEndEvent,
    PossessionChangeEvent,
    PressureAttrs,
    PressureEvent,
    ShotAttrs,
    ShotEvent,
    ShotOutcome,
    ShotSituation,
    SubstitutionAttrs,
    SubstitutionEvent,
    TackleEvent,
)
from matchlens.models.match import MatchMetadata
from matchlens.models.pitch import PITCH_LENGTH_M, PITCH_WIDTH_M
from matchlens.models.tracking import TrackingFrame
from matchlens.sim.event_log import EventLog
from matchlens.sim.lanes import LaneContact, lane_contacts, pass_apex
from matchlens.sim.scenarios import Injection, StyleShift
from matchlens.sim.space import (
    CENTRE_LATERAL_M,
    CENTRE_SPOT,
    HALFWAY_M,
    PENALTY_SPOT_DISTANCE_M,
    Period,
    Spot,
    attacks_right,
    clamp_to_pitch,
    from_attacking_frame,
    in_penalty_area,
    opponent,
    to_attacking_frame,
    to_point,
)
from matchlens.sim.squad import PlayerState, TeamState
from matchlens.sim.tuning import DEFAULT_TUNING, EngineTuning, MsRange
from matchlens.sim.world import STEP_MS, Contact, MatchWorld

Action = Literal["pass", "carry", "dribble", "shot"]
SetPiece = Literal["corner", "penalty", "direct_free_kick", "free_kick_cross"]

SIDES: tuple[TeamSide, TeamSide] = ("home", "away")
PERIODS: tuple[Period, Period] = (1, 2)
REGULATION_PERIOD_MS = REGULATION_PERIOD_MINUTES * MS_PER_MINUTE
SHOT_OUTCOMES_WITHOUT_GOAL: tuple[ShotOutcome, ...] = ("blocked", "saved", "off_target", "woodwork")
FINAL_THIRD_START_M = PITCH_LENGTH_M * 2 / 3
OWN_THIRD_END_M = PITCH_LENGTH_M / 3
GOAL_KICK_DEPTH_M = 5.5
CORNER_INSET_M = 1.0
BOX_TARGET_DEPTH_M = (94.0, 100.0)
BOX_TARGET_LATERAL_M = (28.0, 40.0)
CROSSING_CHANNEL_M = 14.0
BYLINE_ZONE_M = 12.0
FORCED_MIN_FORWARD_GAIN_M = 3.0


class MatchEngine:
    def __init__(  # noqa: PLR0913 - retain offline options and optional streaming hooks
        self,
        metadata: MatchMetadata,
        rng: Random,
        tuning: EngineTuning = DEFAULT_TUNING,
        script: Sequence[Injection] = (),
        *,
        record_tracking: bool = True,
        on_input: Callable[[BaseEvent | TrackingFrame], None] | None = None,
        retain_history: bool = True,
    ) -> None:
        self._rng = rng
        self._tuning = tuning
        self._log = EventLog(metadata.match_id)
        self._teams: dict[TeamSide, TeamState] = {
            "home": TeamState.from_team(metadata.home),
            "away": TeamState.from_team(metadata.away),
        }
        self.world = MatchWorld(metadata.match_id, self._teams, record=record_tracking)
        self.world.on_frame = on_input
        self.world.retain_history = retain_history
        self._log.on_event = on_input
        self._log.retain_history = retain_history
        self._log.on_advance = self._advance_world
        self._possession: TeamSide = "home"
        self._carrier = self._teams["home"].most_advanced()
        self._ball = CENTRE_SPOT
        self._pressure = 0.0
        self._transition_actions = 0
        self._assist_pass: PassEvent | None = None
        self._set_piece: SetPiece | None = None
        self._pending_script = sorted(
            script, key=lambda injection: (injection.period, injection.due_ms)
        )
        self._forced_attack: TeamSide | None = None

    def run(self) -> list[MatchEvent]:
        first_kickoff = self._rng.choice(SIDES)
        for period in PERIODS:
            self._play_period(period, first_kickoff if period == 1 else opponent(first_kickoff))
        return self._log.events

    def _play_period(self, period: Period, kickoff_side: TeamSide) -> None:
        self._log.start_period(period)
        self.world.start_period(period)
        period_end_ms = REGULATION_PERIOD_MS + self._uniform_ms(self._tuning.added_time_ms)
        if period == 2:
            self._plan_substitutions()
        self._kick_off(kickoff_side)
        while self._log.ms < period_end_ms:
            self._run_due_script()
            self._play_action()
        self._log.emit(PeriodEndEvent if period == 1 else MatchEndEvent)

    def _play_action(self) -> None:
        self._resolve_control_contact()
        self._prepare_control()
        if self.world.restart_side is not None:
            self._pass()
            return
        if self._set_piece is not None:
            set_piece, self._set_piece = self._set_piece, None
            self._take_set_piece(set_piece)
            return
        forced = self._is_forced_attack()
        if not forced and self._apply_defensive_pressure():
            return
        match self._choose_forced_action() if forced else self._choose_action():
            case "shot":
                self._shoot(situation="open_play")
            case "carry":
                self._carry()
            case "dribble":
                self._dribble()
            case "pass":
                self._pass()
        self._transition_actions = max(0, self._transition_actions - 1)
        self._resolve_control_contact()

    def _attacking_right(self, side: TeamSide) -> bool:
        return attacks_right(side, self._log.period)

    def _in_frame(self, spot: Spot, side: TeamSide) -> Spot:
        return to_attacking_frame(spot, attacking_right=self._attacking_right(side))

    def _from_frame(self, frame_spot: Spot, side: TeamSide) -> Spot:
        return from_attacking_frame(frame_spot, attacking_right=self._attacking_right(side))

    def _shape(self, side: TeamSide) -> dict[str, Spot]:
        return self.world.positions(side)

    @property
    def _ball(self) -> Spot:
        return self.world.ball

    @_ball.setter
    def _ball(self, spot: Spot) -> None:
        self.world.place(spot)

    def _advance_world(self, period: Period, ms: int, duration: int) -> None:
        if self.world.control_contact is None:
            self.world.owner_id = self._carrier.player_id
            self.world.side = self._possession
        self.world.advance(period, ms, duration)

    def _resolve_control_contact(self) -> bool:
        contact = self.world.control_contact
        if contact is None or contact.player_id is None:
            return False
        self.world.control_contact = None
        side: TeamSide = (
            "home"
            if any(
                player.player_id == contact.player_id for player in self._teams["home"].on_pitch()
            )
            else "away"
        )
        previous = self._carrier.player_id
        self._change_possession(
            side, self._teams[side].player(contact.player_id), self.world.ball, transition=True
        )
        self.world.owner_id, self.world.side = self._carrier.player_id, side
        self._set_piece = None
        return previous != self._carrier.player_id

    def _prepare_control(
        self, target: Spot | None = None, action: Literal["pass", "shot"] = "pass"
    ) -> bool:
        if self._resolve_control_contact():
            return False
        self.world.owner_id = self._carrier.player_id
        self.world.side = self._possession
        self.world.dead_ball = False
        self.world.face_target = target
        self.world.invalidate_targets()
        # Even a distant restart taker must walk to the ball. No snap to the
        # next event's origin; the recorded world advances during the approach.
        for _ in range(300):
            if self.world.ready(target):
                break
            self._log.advance(100)
            if self._resolve_control_contact():
                return False
        if not self.world.ready(target):
            return False
        if target is not None:
            self.world.prepare(action)
            self._log.advance(200)
            if self._resolve_control_contact():
                return False
        return self.world.ready(target)

    def _run_flight(self) -> Contact:
        while self.world.contact is None:
            self._log.advance(STEP_MS)
        contact = self.world.contact
        self.world.finish_flight()
        return contact

    def _nearest(self, side: TeamSide, spot: Spot, *, outfield_only: bool = False) -> PlayerState:
        shape = self._shape(side)
        team = self._teams[side]
        candidates = team.outfield() if outfield_only else team.on_pitch()
        return min(candidates, key=lambda player: shape[player.player_id].distance_to(spot))

    def _choose_action(self) -> Action:
        tuning = self._tuning
        carrier = self._carrier
        if carrier.is_goalkeeper:
            return "pass"
        frame_ball = self._in_frame(self._ball, self._possession)
        style = self._teams[self._possession].team.style
        transition = self._transition_actions > 0

        shot_weight = 0.0
        if frame_ball.x >= tuning.shot_min_progress_m:
            shot_weight = tuning.shot_weight_scale * self._open_play_xg() ** tuning.shot_xg_exponent
        pace = carrier.player.traits.pace / 100
        carry_weight = (
            tuning.carry_weight
            * (0.6 + 0.8 * pace)
            * (1 + tuning.transition_carry_boost * transition)
            * (1 - tuning.carry_pressure_damping * self._pressure)
        )
        role_factor = {"W": 1.0, "AM": 1.0, "ST": 0.8, "CM": 0.4}.get(carrier.player.role, 0.15)
        zone_factor = (
            tuning.final_third_dribble_boost if frame_ball.x > FINAL_THIRD_START_M else 0.7
        )
        dribble_weight = tuning.dribble_weight * role_factor * zone_factor
        pass_weight = tuning.pass_weight * (
            1 + tuning.pass_possession_style_weight * style.possession
        )

        actions: tuple[Action, ...] = ("shot", "carry", "dribble", "pass")
        weights = (shot_weight, carry_weight, dribble_weight, pass_weight)
        return self._rng.choices(actions, weights=weights)[0]

    def _open_play_xg(self) -> float:
        geometry = shot_geometry(
            to_point(self._ball), attacking_right=self._attacking_right(self._possession)
        )
        return expected_goals(geometry, "foot", "open_play")

    def _apply_defensive_pressure(self) -> bool:
        tuning = self._tuning
        defending_side = opponent(self._possession)
        press = self._teams[defending_side].team.style.press
        probability = tuning.pressure_base + tuning.pressure_style_weight * press
        attacking_depth = self._in_frame(self._ball, self._possession).x
        if attacking_depth < tuning.build_up_zone_end_m:
            probability *= tuning.build_up_press_floor + tuning.build_up_press_style_weight * press
        elif attacking_depth > FINAL_THIRD_START_M:
            probability *= tuning.final_third_pressure_factor
        if self._rng.random() >= probability:
            self._pressure = self._rng.uniform(0.0, 0.25)
            return False
        presser = self._nearest(defending_side, self._ball, outfield_only=True)
        if self._shape(defending_side)[presser.player_id].distance_to(self._ball) > 2.5:
            self._pressure = 0.0
            return False
        self._log.emit(
            PressureEvent,
            team_id=defending_side,
            player_id=presser.player_id,
            location=to_point(self._ball),
            attrs=PressureAttrs(target_player_id=self._carrier.player_id),
        )
        if self._commits_foul(presser, tuning.pressure_foul_share):
            self._foul(presser, defending_side, self._carrier)
            return True
        self._pressure = self._rng.uniform(0.5, 1.0)
        return False

    def _defensive_challenge(self) -> None:
        tuning = self._tuning
        defending_side = opponent(self._possession)
        defender = self._nearest(defending_side, self._ball, outfield_only=True)
        if self._shape(defending_side)[defender.player_id].distance_to(self._ball) > 2.0:
            return
        attacker = self._carrier
        if self._commits_foul(defender, tuning.foul_share_of_challenges):
            self._foul(defender, defending_side, attacker)
            return
        skill_gap = defender.player.traits.defending - attacker.player.traits.pace
        won = self._rng.random() < tuning.tackle_base_win + tuning.tackle_skill_weight * skill_gap
        self._log.emit(
            TackleEvent,
            team_id=defending_side,
            player_id=defender.player_id,
            location=to_point(self._ball),
            outcome="won" if won else "lost",
            attrs=DuelAttrs(opponent_id=attacker.player_id),
        )
        if won:
            self._change_possession(defending_side, defender, self._ball, transition=True)

    def _pass(self) -> None:
        forward_receiver = self._forward_receiver() if self._is_forced_attack() else None
        if forward_receiver is not None:
            target = self._shape(self._possession)[forward_receiver.player_id]
            self._deliver_pass(forward_receiver, target, height="ground")
            return
        receiver, target = self._choose_receiver()
        self._deliver_pass(receiver, target, height=self._pass_height(target))

    def _choose_receiver(self) -> tuple[PlayerState, Spot]:
        tuning = self._tuning
        side = self._possession
        shape = self._shape(side)
        directness = self._teams[side].team.style.directness
        frame_ball = self._in_frame(self._ball, side)
        own_third = frame_ball.x < OWN_THIRD_END_M

        candidates: list[PlayerState] = []
        weights: list[float] = []
        for teammate in self._teams[side].on_pitch():
            if teammate is self._carrier:
                continue
            if self._receiver_offside(teammate):
                continue
            spot = shape[teammate.player_id]
            distance = self._ball.distance_to(spot)
            if not tuning.pass_min_length_m <= distance <= tuning.pass_max_length_m:
                continue
            forward_gain = self._in_frame(spot, side).x - frame_ball.x
            weight = math.exp(-distance / tuning.pass_distance_scale_m)
            weight *= (
                1 + tuning.forward_pass_directness_weight * directness * max(0.0, forward_gain) / 15
            )
            if forward_gain < -5:
                weight *= 1 - tuning.backward_pass_directness_damping * directness
            if self._lane_contacts(spot):
                weight *= 0.12
            if teammate.is_goalkeeper:
                weight *= (
                    tuning.goalkeeper_pass_weight_own_third
                    if own_third
                    else tuning.goalkeeper_pass_weight_elsewhere
                )
            candidates.append(teammate)
            weights.append(weight)

        if not candidates:
            nearest = min(
                (
                    teammate
                    for teammate in self._teams[side].on_pitch()
                    if teammate is not self._carrier
                ),
                key=lambda teammate: shape[teammate.player_id].distance_to(self._ball),
            )
            return nearest, shape[nearest.player_id]
        receiver = self._rng.choices(candidates, weights=weights)[0]
        spot = shape[receiver.player_id]
        noise = tuning.pass_target_noise_m
        target = Spot(spot.x + self._rng.gauss(0, noise), spot.y + self._rng.gauss(0, noise))
        return receiver, clamp_to_pitch(target)

    def _lane_contacts(self, target: Spot, *, apex_m: float = 0.0) -> list[LaneContact]:
        defending_side = opponent(self._possession)
        shape = self._shape(defending_side)
        defenders = {
            player.player_id: shape[player.player_id]
            for player in self._teams[defending_side].on_pitch()
        }
        return lane_contacts(self._ball, target, defenders, apex_m=apex_m)

    def _pass_height(self, target: Spot) -> PassHeight:
        length = self._ball.distance_to(target)
        frame_ball = self._in_frame(self._ball, self._possession)
        is_cross = (
            in_penalty_area(self._in_frame(target, self._possession))
            and abs(frame_ball.y - CENTRE_LATERAL_M) > CENTRE_LATERAL_M - CROSSING_CHANNEL_M
        )
        heights: tuple[PassHeight, ...] = ("ground", "low", "high")
        if is_cross:
            weights = (0.15, 0.25, 0.6)
        elif length < 25:
            weights = (0.9, 0.1, 0.0)
        elif length < 40:
            weights = (0.5, 0.3, 0.2)
        else:
            weights = (0.0, 0.3, 0.7)
        return self._rng.choices(heights, weights=weights)[0]

    def _pass_success_probability(self, length: float, height: PassHeight, target: Spot) -> float:
        tuning = self._tuning
        frame_target = self._in_frame(target, self._possession)
        probability = (
            tuning.pass_base_success
            - tuning.pass_length_penalty * max(0.0, length - tuning.pass_free_length_m)
            - tuning.pass_pressure_penalty * self._pressure
            + tuning.pass_skill_weight * (self._carrier.player.traits.passing - 70)
        )
        if height == "low":
            probability -= tuning.low_pass_penalty
        elif height == "high":
            probability -= tuning.high_pass_penalty
        if frame_target.x > FINAL_THIRD_START_M:
            probability -= tuning.final_third_pass_penalty
        if in_penalty_area(frame_target):
            probability -= tuning.box_pass_penalty
        return min(max(probability, tuning.min_pass_success), tuning.max_pass_success)

    def _deliver_pass(self, receiver: PlayerState, target: Spot, *, height: PassHeight) -> bool:
        side = self._possession
        passer = self._carrier
        self.world.receive_target = receiver.player_id, target
        if not self._prepare_control(target):
            return False
        origin = self._ball
        length = origin.distance_to(target)
        if self._lane_contacts(target) and self._is_forced_attack():
            height = "high"
        offside_players = {
            player.player_id
            for player in self._teams[side].on_pitch()
            if self._receiver_offside(player)
        }
        flight = self.world.launch(
            target,
            action="pass",
            receiver_id=receiver.player_id,
            apex=pass_apex(length, height),
        )
        contact = self._run_flight()
        recovered_by_passer = (
            contact.outcome == "complete" and contact.player_id == passer.player_id
        )
        actual_receiver = (
            self._teams[side].player(contact.player_id)
            if contact.outcome == "complete"
            and contact.player_id is not None
            and not recovered_by_passer
            else receiver
        )
        outcome: PassOutcome = (
            "offside"
            if contact.outcome == "complete"
            and not recovered_by_passer
            and actual_receiver.player_id in offside_players
            else "complete"
            if contact.outcome == "complete" and not recovered_by_passer
            else "out"
            if contact.outcome == "out"
            else "incomplete"
        )
        end = contact.spot
        event = self._log.emit(
            PassEvent,
            team_id=side,
            player_id=passer.player_id,
            location=to_point(origin),
            end_location=to_point(end),
            outcome=outcome,
            attrs=PassAttrs(
                receiver_id=actual_receiver.player_id,
                length_m=round(origin.distance_to(end), 1),
                height=height,
                under_pressure=self._pressure >= self._tuning.pressured_threshold,
                ball_speed_kmh=round(flight.speed * 3.6, 1),
            ),
        )
        if recovered_by_passer:
            # A kick blocked back into the releasing player is a failed pass
            # attempt followed by recovery, never a pass to themselves.
            self._assist_pass = None
            self._pressure = 0.5
            return False
        if contact.outcome == "intercepted" and contact.player_id is not None:
            self._intercept_pass(LaneContact(contact.player_id, end, 1.0))
            return False

        match outcome:
            case "complete":
                self._carrier = actual_receiver
                self._pressure = 0.0
                self._assist_pass = event
                return True
            case "offside":
                self._award_free_kick(opponent(side), end, preferred_taker=None)
            case "out":
                self._ball_out(side, passer, end)
            case "incomplete":
                self._loose_ball(end, interceptable=True)
        return False

    def _receiver_offside(self, receiver: PlayerState) -> bool:
        side = self._possession
        receiver_depth = self._in_frame(self._shape(side)[receiver.player_id], side).x
        depths = sorted(
            (self._in_frame(spot, side).x for spot in self._shape(opponent(side)).values()),
            reverse=True,
        )
        line = depths[1] if len(depths) > 1 else PITCH_LENGTH_M
        return receiver_depth > max(HALFWAY_M, self._in_frame(self._ball, side).x, line) + 0.1

    def _intercept_pass(self, contact: LaneContact) -> None:
        side = opponent(self._possession)
        interceptor = self._teams[side].player(contact.player_id)
        self._ball = contact.spot
        self._assist_pass = None
        self._log.emit(
            InterceptionEvent,
            team_id=side,
            player_id=interceptor.player_id,
            location=to_point(contact.spot),
        )
        self._change_possession(side, interceptor, contact.spot, transition=True)

    def _ball_speed_kmh(self, length: float, height: PassHeight) -> float:
        base = 35.0 + length * 1.0 if height == "ground" else 45.0 + length * 0.6
        return round(min(max(base + self._rng.gauss(0, 6), 20.0), 110.0), 1)

    def _out_of_play_spot(self, target: Spot) -> Spot:
        frame_target = self._in_frame(target, self._possession)
        if frame_target.x > PITCH_LENGTH_M - BYLINE_ZONE_M:
            frame_out = Spot(PITCH_LENGTH_M, frame_target.y)
        else:
            touchline = 0.0 if frame_target.y < CENTRE_LATERAL_M else PITCH_WIDTH_M
            frame_out = Spot(frame_target.x, touchline)
        return self._from_frame(frame_out, self._possession)

    def _loose_ball(self, spot: Spot, *, interceptable: bool) -> None:
        tuning = self._tuning
        attacking_side = self._possession
        defending_side = opponent(attacking_side)
        self._ball = spot
        if interceptable and self._rng.random() < tuning.interception_share:
            interceptor = self._nearest(defending_side, spot)
            self._log.emit(
                InterceptionEvent,
                team_id=defending_side,
                player_id=interceptor.player_id,
                location=to_point(spot),
            )
            self._log.advance(self._uniform_ms(tuning.duel_duration_ms))
            self._change_possession(defending_side, interceptor, spot, transition=True)
            return
        if self._rng.random() < tuning.loose_ball_defender_share:
            winner = self._nearest(defending_side, spot)
            self._change_possession(defending_side, winner, spot, transition=True)
            return
        self._carrier = self._nearest(attacking_side, spot, outfield_only=True)
        self._pressure = 0.0

    def _carry(self) -> None:
        tuning = self._tuning
        side = self._possession
        carrier = self._carrier
        frame_ball = self._in_frame(self._ball, side)
        pace_factor = 0.7 + 0.6 * self._carrier.player.traits.pace / 100
        if self._log.period == 2:
            pace_factor *= tuning.second_half_pace_factor
        distance = self._rng.uniform(tuning.carry_min_m, tuning.carry_max_m) * pace_factor
        if self._transition_actions > 0:
            distance *= 1 + tuning.transition_carry_boost
        heading = self._rng.gauss(0, tuning.carry_heading_sd_rad)
        if self._is_forced_attack():
            heading = math.atan2(CENTRE_LATERAL_M - frame_ball.y, PITCH_LENGTH_M - frame_ball.x)
        elif frame_ball.x > FINAL_THIRD_START_M:
            distance *= tuning.final_third_carry_factor
            heading += (CENTRE_LATERAL_M - frame_ball.y) / 120
        frame_end = Spot(
            min(frame_ball.x + distance * math.cos(heading), PITCH_LENGTH_M - 2.0),
            min(max(frame_ball.y + distance * math.sin(heading), 1.0), PITCH_WIDTH_M - 1.0),
        )
        end = self._from_frame(frame_end, side)
        origin = self._ball
        travelled = origin.distance_to(end)
        self.world.carry_target = end
        self.world.invalidate_targets()
        self._log.advance(
            tuning.carry_duration_base_ms + int(travelled * tuning.carry_duration_per_m_ms)
        )
        self.world.carry_target = None
        end = self._ball
        self._log.emit(
            CarryEvent,
            team_id=side,
            player_id=carrier.player_id,
            location=to_point(origin),
            end_location=to_point(end),
            attrs=CarryAttrs(distance_m=round(origin.distance_to(end), 1)),
        )
        if self._resolve_control_contact():
            return
        challenge_probability = (
            tuning.carry_challenge_base + tuning.carry_challenge_pressure_weight * self._pressure
        )
        if in_penalty_area(self._in_frame(end, side)):
            challenge_probability *= tuning.penalty_area_challenge_factor
        if not self._is_forced_attack() and self._rng.random() < challenge_probability:
            self._defensive_challenge()

    def _dribble(self) -> None:
        tuning = self._tuning
        side = self._possession
        defending_side = opponent(side)
        defender = self._nearest(defending_side, self._ball, outfield_only=True)
        if self._shape(defending_side)[defender.player_id].distance_to(self._ball) > 2.0:
            self._carry()
            return
        attacker = self._carrier
        if self._commits_foul(defender, tuning.foul_share_of_challenges):
            self._foul(defender, defending_side, attacker)
            return
        skill_gap = attacker.player.traits.pace - defender.player.traits.defending
        won = self._rng.random() < tuning.dribble_base_win + tuning.dribble_skill_weight * skill_gap
        self._log.emit(
            DuelEvent,
            team_id=side,
            player_id=attacker.player_id,
            location=to_point(self._ball),
            outcome="won" if won else "lost",
            attrs=DuelAttrs(opponent_id=defender.player_id),
        )
        self._log.advance(self._uniform_ms(tuning.duel_duration_ms))
        if not won:
            self._change_possession(defending_side, defender, self._ball, transition=True)
            return
        frame_ball = self._in_frame(self._ball, side)
        gain = self._rng.uniform(*tuning.dribble_gain_m)
        self.world.carry_target = self._from_frame(
            Spot(min(frame_ball.x + gain, PITCH_LENGTH_M - 2.0), frame_ball.y), side
        )
        self.world.invalidate_targets()
        self._log.advance(1500)
        self.world.carry_target = None
        self._pressure = 0.0

    def _shoot(self, *, situation: ShotSituation, body_part: BodyPart | None = None) -> None:
        tuning = self._tuning
        side = self._possession
        defending_side = opponent(side)
        shooter = self._carrier
        aim = self._shot_end_spot("goal")
        if not self._prepare_control(aim, "shot"):
            return
        origin = self._ball
        if body_part is None:
            crossed_in = self._assist_pass is not None and self._assist_pass.attrs.height == "high"
            header = crossed_in and self._rng.random() < tuning.header_after_cross_share
            body_part = "head" if header else "foot"

        geometry = shot_geometry(to_point(origin), attacking_right=self._attacking_right(side))
        xg = expected_goals(geometry, body_part, situation)
        keeper = self._teams[defending_side].goalkeeper()
        goal_probability = sigmoid(
            logit(xg)
            + tuning.finishing_weight * (shooter.player.traits.finishing - 75) / 25
            - tuning.keeper_weight * (keeper.player.traits.defending - 80) / 20
            - tuning.pressured_shot_penalty * self._pressure
        )
        outcome: ShotOutcome = (
            "goal" if self._is_forced_attack() else self._shot_outcome(goal_probability, situation)
        )
        assist = self._assist_pass if self._assisted_by_last_pass(shooter) else None
        aim = self._shot_end_spot("goal" if outcome == "blocked" else outcome)
        speed = self._shot_speed_kmh(body_part, shooter)
        self.world.launch(
            aim,
            action="shot",
            speed=speed / 3.6,
            target_height=2.44 if outcome == "woodwork" else self._rng.uniform(0.25, 1.7),
        )
        contact = self._run_flight()
        outcomes: dict[str, ShotOutcome] = {
            "goal": "goal",
            "saved": "saved",
            "blocked": "blocked",
            "woodwork": "woodwork",
        }
        outcome = outcomes.get(contact.outcome, "off_target")
        end_spot = contact.spot
        blocker = (
            next(
                player
                for team in self._teams.values()
                for player in team.on_pitch()
                if player.player_id == contact.player_id
            )
            if contact.outcome == "blocked" and contact.player_id is not None
            else None
        )

        shot = self._log.emit(
            ShotEvent,
            team_id=side,
            player_id=shooter.player_id,
            location=to_point(origin),
            end_location=to_point(end_spot),
            outcome=outcome,
            attrs=ShotAttrs(
                body_part=body_part,
                shot_speed_kmh=speed,
                situation=situation,
                assist_event_id=assist.event_id if assist else None,
            ),
        )
        self._assist_pass = None

        match outcome:
            case "goal":
                self._forced_attack = None
                self._log.emit(
                    GoalEvent,
                    team_id=side,
                    player_id=shooter.player_id,
                    attrs=GoalAttrs(
                        scorer_id=shooter.player_id,
                        assist_id=assist.player_id if assist else None,
                        shot_event_id=shot.event_id,
                    ),
                )
                self._stoppage(tuning.goal_stoppage_ms)
                self._kick_off(defending_side)
            case "saved":
                self._change_possession(defending_side, keeper, end_spot, transition=False)
            case "blocked":
                if blocker is not None and any(
                    player.player_id == blocker.player_id for player in self._teams[side].on_pitch()
                ):
                    self._rebound(end_spot)
                else:
                    self._blocked_shot(end_spot, shooter, blocker)
            case "off_target":
                self._ball_out(side, shooter, end_spot)
            case "woodwork":
                self._rebound(end_spot)

    def _resolve_shot_lane(
        self, outcome: ShotOutcome, body_part: BodyPart, situation: ShotSituation
    ) -> tuple[ShotOutcome, Spot, PlayerState | None]:
        target = self._shot_end_spot("goal" if outcome == "blocked" else outcome)
        contacts = self._lane_contacts(target, apex_m=0.7 if body_part == "head" else 0.45)
        if contacts and situation != "penalty":
            contact = contacts[0]
            blocker = self._teams[opponent(self._possession)].player(contact.player_id)
            if blocker.is_goalkeeper:
                return "saved", contact.spot, None
            return "blocked", contact.spot, blocker
        if outcome == "blocked":
            # Don't invent a nearby block when no defender occupies the lane.
            return "off_target", self._shot_end_spot("off_target"), None
        return outcome, target, None

    def _blocked_shot(self, spot: Spot, shooter: PlayerState, blocker: PlayerState | None) -> None:
        side = opponent(self._possession)
        last_touch = blocker or self._nearest(side, spot, outfield_only=True)
        self._log.emit(
            PressureEvent,
            team_id=side,
            player_id=last_touch.player_id,
            location=to_point(spot),
            attrs=PressureAttrs(target_player_id=shooter.player_id),
        )
        if self._rng.random() < self._tuning.block_to_corner_share:
            self.world.owner_id, self.world.side = last_touch.player_id, side
            self.world.launch(self._shot_end_spot("off_target"), action="pass", apex=0.6)
            contact = self._run_flight()
            if contact.outcome == "out":
                self._ball_out(side, last_touch, contact.spot)
            else:
                self._loose_ball(contact.spot, interceptable=False)
        else:
            self._rebound(spot)

    def _assisted_by_last_pass(self, shooter: PlayerState) -> bool:
        return (
            self._assist_pass is not None
            and self._assist_pass.attrs.receiver_id == shooter.player_id
            and self._assist_pass.team_id == self._possession
        )

    def _shot_outcome(self, goal_probability: float, situation: ShotSituation) -> ShotOutcome:
        if self._rng.random() < goal_probability:
            return "goal"
        weights = (
            self._tuning.penalty_miss_weights
            if situation == "penalty"
            else self._tuning.non_goal_outcome_weights
        )
        return self._rng.choices(SHOT_OUTCOMES_WITHOUT_GOAL, weights=weights)[0]

    def _shot_end_spot(self, outcome: ShotOutcome) -> Spot:
        side = self._possession
        frame_ball = self._in_frame(self._ball, side)
        if outcome == "blocked":
            frame_end = Spot(
                min(frame_ball.x + self._rng.uniform(1, 3), PITCH_LENGTH_M), frame_ball.y
            )
        elif outcome == "off_target":
            wide = self._rng.uniform(4.5, 12.0) * self._rng.choice((-1, 1))
            frame_end = Spot(PITCH_LENGTH_M, CENTRE_LATERAL_M + wide)
        elif outcome == "woodwork":
            frame_end = Spot(PITCH_LENGTH_M, CENTRE_LATERAL_M + self._rng.choice((-3.66, 3.66)))
        else:
            frame_end = Spot(PITCH_LENGTH_M, CENTRE_LATERAL_M + self._rng.uniform(-3.4, 3.4))
        return self._from_frame(frame_end, side)

    def _shot_speed_kmh(self, body_part: BodyPart, shooter: PlayerState) -> float:
        if body_part == "head":
            return round(self._rng.uniform(40.0, 70.0), 1)
        power = 75.0 + 0.4 * (shooter.player.traits.finishing - 60)
        return round(min(max(power + self._rng.gauss(0, 12), 45.0), 130.0), 1)

    def _rebound(self, spot: Spot) -> None:
        if self._rng.random() < self._tuning.rebound_attacker_share:
            self._ball = spot
            self._carrier = self._nearest(self._possession, spot, outfield_only=True)
            self._pressure = 0.5
            return
        self._loose_ball(spot, interceptable=False)

    def _goalkeeper_spot(self, side: TeamSide) -> Spot:
        return self._from_frame(Spot(GOAL_KICK_DEPTH_M + 1.0, CENTRE_LATERAL_M), side)

    def _commits_foul(self, defender: PlayerState, base_probability: float) -> bool:
        tuning = self._tuning
        probability = base_probability
        if in_penalty_area(self._in_frame(self._ball, self._possession)):
            probability *= tuning.penalty_area_foul_factor
        if defender.yellow_cards:
            probability *= tuning.booked_player_foul_factor
        return self._rng.random() < probability

    def _foul(self, offender: PlayerState, offender_side: TeamSide, victim: PlayerState) -> None:
        victim_side = opponent(offender_side)
        location = self._ball
        self._log.emit(
            FoulEvent,
            team_id=offender_side,
            player_id=offender.player_id,
            location=to_point(location),
            attrs=FoulAttrs(fouled_player_id=victim.player_id),
        )
        self._book(offender, offender_side)
        if in_penalty_area(self._in_frame(location, victim_side)):
            self._award_penalty(victim_side)
            return
        self._award_free_kick(victim_side, location, preferred_taker=victim)

    def _book(self, offender: PlayerState, side: TeamSide) -> None:
        tuning = self._tuning
        roll = self._rng.random()
        outcome: CardOutcome
        if roll < tuning.straight_red_share and not offender.is_goalkeeper:
            outcome, reason = "red", "serious foul play"
        elif roll < tuning.straight_red_share + tuning.yellow_share:
            second = offender.yellow_cards == 1 and not offender.is_goalkeeper
            outcome, reason = ("second_yellow", "second caution") if second else ("yellow", "foul")
        else:
            return
        self._log.emit(
            CardEvent,
            team_id=side,
            player_id=offender.player_id,
            outcome=outcome,
            attrs=CardAttrs(reason=reason),
        )
        if outcome == "yellow":
            offender.yellow_cards += 1
        else:
            offender.sent_off = True

    def _kick_off(self, side: TeamSide) -> None:
        taker = self._teams[side].most_advanced()
        self._possession = side
        self._carrier = taker
        self._ball = CENTRE_SPOT
        self.world.kickoff(taker.player_id, side)
        self._prepare_control()
        self._pressure = 0.0
        self._transition_actions = 0
        self._assist_pass = None
        self._log.emit(
            KickoffEvent, team_id=side, player_id=taker.player_id, location=to_point(CENTRE_SPOT)
        )

    def _ball_out(self, last_side: TeamSide, last_player: PlayerState, spot: Spot) -> None:
        boundary = clamp_to_pitch(spot)
        self._log.emit(
            BallOutEvent,
            team_id=last_side,
            player_id=last_player.player_id,
            location=to_point(boundary),
        )
        self._stoppage(self._tuning.ball_out_stoppage_ms)
        restart_side = opponent(last_side)
        frame_spot = self._in_frame(boundary, restart_side)
        if frame_spot.x >= PITCH_LENGTH_M - 0.1:
            self._award_corner(restart_side, frame_spot.y)
        elif frame_spot.x <= 0.1:
            keeper = self._teams[restart_side].goalkeeper()
            spot = self._from_frame(Spot(GOAL_KICK_DEPTH_M, CENTRE_LATERAL_M), restart_side)
            self._change_possession(restart_side, keeper, spot, transition=False)
        else:
            inset = CORNER_INSET_M if frame_spot.y < CENTRE_LATERAL_M else -CORNER_INSET_M
            throw_spot = self._from_frame(Spot(frame_spot.x, frame_spot.y + inset), restart_side)
            thrower = self._nearest(restart_side, throw_spot, outfield_only=True)
            self._change_possession(restart_side, thrower, throw_spot, transition=False)

    def _award_corner(self, side: TeamSide, frame_lateral: float) -> None:
        lateral = (
            CORNER_INSET_M if frame_lateral < CENTRE_LATERAL_M else PITCH_WIDTH_M - CORNER_INSET_M
        )
        spot = self._from_frame(Spot(PITCH_LENGTH_M - CORNER_INSET_M, lateral), side)
        takers = [
            player
            for player in self._teams[side].outfield()
            if player.player.role in ("W", "FB", "CM", "AM")
        ] or self._teams[side].outfield()
        taker = max(takers, key=lambda player: player.player.traits.passing)
        self._change_possession(side, taker, spot, transition=False)
        self._set_piece = "corner"

    def _award_free_kick(
        self, side: TeamSide, spot: Spot, *, preferred_taker: PlayerState | None
    ) -> None:
        tuning = self._tuning
        self._stoppage(tuning.foul_stoppage_ms)
        taker = (
            preferred_taker
            if preferred_taker is not None and preferred_taker.on_pitch
            else self._nearest(side, spot, outfield_only=True)
        )
        self._change_possession(side, taker, spot, transition=False)
        frame_spot = self._in_frame(spot, side)
        goal_distance = math.hypot(PITCH_LENGTH_M - frame_spot.x, frame_spot.y - CENTRE_LATERAL_M)
        roll = self._rng.random()
        if (
            goal_distance <= tuning.direct_free_kick_max_distance_m
            and roll < tuning.direct_free_kick_share
        ):
            self._set_piece = "direct_free_kick"
        elif frame_spot.x > FINAL_THIRD_START_M and roll < tuning.free_kick_cross_share:
            self._set_piece = "free_kick_cross"

    def _award_penalty(self, side: TeamSide) -> None:
        self._stoppage(self._tuning.foul_stoppage_ms)
        taker = self._teams[side].best_finisher()
        spot = self._from_frame(
            Spot(PITCH_LENGTH_M - PENALTY_SPOT_DISTANCE_M, CENTRE_LATERAL_M), side
        )
        self._change_possession(side, taker, spot, transition=False)
        self._set_piece = "penalty"

    def _take_set_piece(self, set_piece: SetPiece) -> None:
        match set_piece:
            case "penalty":
                self._shoot(situation="penalty", body_part="foot")
            case "direct_free_kick":
                self._carrier = self._teams[self._possession].best_finisher()
                self._shoot(situation="set_piece", body_part="foot")
            case "corner" | "free_kick_cross":
                self._cross_into_box()

    def _cross_into_box(self) -> None:
        side = self._possession
        targets = [
            player
            for player in self._teams[side].outfield()
            if player is not self._carrier and player.player.role in ("CB", "ST", "W", "AM")
        ] or [player for player in self._teams[side].outfield() if player is not self._carrier]
        receiver = self._rng.choice(targets)
        frame_target = Spot(
            self._rng.uniform(*BOX_TARGET_DEPTH_M), self._rng.uniform(*BOX_TARGET_LATERAL_M)
        )
        completed = self._deliver_pass(
            receiver, self._from_frame(frame_target, side), height="high"
        )
        if completed and self._rng.random() < self._tuning.corner_header_share:
            self._shoot(situation="set_piece", body_part="head")

    def _change_possession(
        self, side: TeamSide, carrier: PlayerState, spot: Spot, *, transition: bool
    ) -> None:
        self._ball = spot
        self._carrier = carrier
        self._pressure = 0.0
        self._assist_pass = None
        if side == self._possession:
            return
        self._possession = side
        self._transition_actions = self._tuning.transition_length_actions if transition else 0
        self._log.emit(PossessionChangeEvent, team_id=side)

    def _uniform_ms(self, bounds: MsRange) -> int:
        return self._rng.randint(*bounds)

    def _stoppage(self, bounds: MsRange) -> None:
        self.world.dead_ball = True
        self.world.resetting = self._ball.x <= 0.1 or self._ball.x >= 104.9
        self.world.invalidate_targets()
        self._log.advance(self._uniform_ms(bounds))
        self.world.dead_ball = False
        self.world.resetting = False
        self._make_due_substitutions()

    def _plan_substitutions(self) -> None:
        tuning = self._tuning
        for team in self._teams.values():
            count = self._rng.randint(*tuning.substitutions_per_team)
            team.substitution_times_ms = sorted(
                self._uniform_ms(tuning.substitution_window_ms) for _ in range(count)
            )

    def _make_due_substitutions(self) -> None:
        if self._log.period != 2:
            return
        for side in SIDES:
            team = self._teams[side]
            while team.substitution_times_ms and team.substitution_times_ms[0] <= self._log.ms:
                team.substitution_times_ms.pop(0)
                self._substitute(side, team)

    def _substitute(self, side: TeamSide, team: TeamState) -> None:
        substitutes = team.available_substitutes()
        if not substitutes:
            return
        player_in = self._rng.choice(substitutes)
        replaceable = [player for player in team.outfield() if player is not self._carrier]
        same_position = [
            player for player in replaceable if player.player.position == player_in.player.position
        ]
        player_out = self._rng.choice(same_position or replaceable)
        team.substitute(player_in, player_out)
        self._log.emit(
            SubstitutionEvent,
            team_id=side,
            attrs=SubstitutionAttrs(
                player_in_id=player_in.player_id, player_out_id=player_out.player_id
            ),
        )

    def _is_forced_attack(self) -> bool:
        return self._forced_attack == self._possession

    def _choose_forced_action(self) -> Action:
        if self._carrier.is_goalkeeper:
            return "pass"
        if self._open_play_xg() >= self._tuning.forced_attack_shot_xg:
            return "shot"
        return "pass" if self._forward_receiver() is not None else "carry"

    def _forward_receiver(self) -> PlayerState | None:
        tuning = self._tuning
        side = self._possession
        shape = self._shape(side)
        ball_depth = self._in_frame(self._ball, side).x
        best: PlayerState | None = None
        best_gain = FORCED_MIN_FORWARD_GAIN_M
        for teammate in self._teams[side].outfield():
            spot = shape[teammate.player_id]
            distance = self._ball.distance_to(spot)
            in_range = tuning.pass_min_length_m <= distance <= tuning.forced_pass_max_length_m
            if teammate is self._carrier or not in_range:
                continue
            if self._receiver_offside(teammate):
                continue
            gain = self._in_frame(spot, side).x - ball_depth
            if gain > best_gain:
                best, best_gain = teammate, gain
        return best

    def _run_due_script(self) -> None:
        while (
            self._pending_script
            and self._set_piece is None
            and self._is_due(self._pending_script[0])
        ):
            injection = self._pending_script.pop(0)
            if isinstance(injection, StyleShift):
                self._shift_style(injection)
            elif injection.action == "red_card":
                self._send_off(injection.team)
            else:
                self._start_forced_attack(injection.team)

    def _is_due(self, injection: Injection) -> bool:
        return (injection.period, injection.due_ms) <= (self._log.period, self._log.ms)

    def _shift_style(self, shift: StyleShift) -> None:
        for side in SIDES:
            changes = shift.changes_for(side)
            if not changes:
                continue
            team_state = self._teams[side]
            style = team_state.team.style
            shifted = {
                trait: min(max(getattr(style, trait) + delta, 0.0), 1.0)
                for trait, delta in changes.items()
            }
            team_state.team = team_state.team.model_copy(
                update={"style": style.model_copy(update=shifted)}
            )

    def _send_off(self, side: TeamSide) -> None:
        offender = self._nearest(side, self._ball, outfield_only=True)
        victim = self._nearest(opponent(side), self._ball, outfield_only=True)
        self._log.emit(
            FoulEvent,
            team_id=side,
            player_id=offender.player_id,
            location=to_point(self._ball),
            attrs=FoulAttrs(fouled_player_id=victim.player_id),
        )
        self._log.emit(
            CardEvent,
            team_id=side,
            player_id=offender.player_id,
            outcome="red",
            attrs=CardAttrs(reason="serious foul play"),
        )
        offender.sent_off = True
        self._award_free_kick(opponent(side), self._ball, preferred_taker=victim)

    def _start_forced_attack(self, side: TeamSide) -> None:
        self._forced_attack = side
