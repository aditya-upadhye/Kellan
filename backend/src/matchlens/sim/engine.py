import math
from random import Random
from typing import Literal

from matchlens.metrics.xg import expected_goals, logit, shot_geometry, sigmoid
from matchlens.models.base import TeamSide
from matchlens.models.clock import MS_PER_MINUTE, REGULATION_PERIOD_MINUTES
from matchlens.models.events import (
    BallOutEvent,
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
from matchlens.sim.event_log import EventLog
from matchlens.sim.shape import team_shape
from matchlens.sim.space import (
    CENTRE_LATERAL_M,
    CENTRE_SPOT,
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

Action = Literal["pass", "carry", "dribble", "shot"]
SetPiece = Literal["corner", "penalty", "direct_free_kick", "free_kick_cross"]

SIDES: tuple[TeamSide, TeamSide] = ("home", "away")
PERIODS: tuple[Period, Period] = (1, 2)
REGULATION_PERIOD_MS = REGULATION_PERIOD_MINUTES * MS_PER_MINUTE
SHOT_OUTCOMES_WITHOUT_GOAL: tuple[ShotOutcome, ...] = ("blocked", "saved", "off_target", "woodwork")
FINAL_THIRD_START_M = PITCH_LENGTH_M * 2 / 3
OWN_THIRD_END_M = PITCH_LENGTH_M / 3
GOAL_KICK_DEPTH_M = 5.5
CORNER_INSET_M = 0.5
BOX_TARGET_DEPTH_M = (94.0, 100.0)
BOX_TARGET_LATERAL_M = (28.0, 40.0)
CROSSING_CHANNEL_M = 14.0
BYLINE_ZONE_M = 12.0


class MatchEngine:
    def __init__(
        self, metadata: MatchMetadata, rng: Random, tuning: EngineTuning = DEFAULT_TUNING
    ) -> None:
        self._rng = rng
        self._tuning = tuning
        self._log = EventLog(metadata.match_id)
        self._teams: dict[TeamSide, TeamState] = {
            "home": TeamState.from_team(metadata.home),
            "away": TeamState.from_team(metadata.away),
        }
        self._possession: TeamSide = "home"
        self._carrier = self._teams["home"].most_advanced()
        self._ball = CENTRE_SPOT
        self._pressure = 0.0
        self._transition_actions = 0
        self._assist_pass: PassEvent | None = None
        self._set_piece: SetPiece | None = None

    def run(self) -> list[MatchEvent]:
        first_kickoff = self._rng.choice(SIDES)
        for period in PERIODS:
            self._play_period(period, first_kickoff if period == 1 else opponent(first_kickoff))
        return self._log.events

    def _play_period(self, period: Period, kickoff_side: TeamSide) -> None:
        self._log.start_period(period)
        period_end_ms = REGULATION_PERIOD_MS + self._uniform_ms(self._tuning.added_time_ms)
        if period == 2:
            self._plan_substitutions()
        self._kick_off(kickoff_side)
        while self._log.ms < period_end_ms:
            self._play_action()
        self._log.emit(PeriodEndEvent if period == 1 else MatchEndEvent)

    def _play_action(self) -> None:
        if self._set_piece is not None:
            set_piece, self._set_piece = self._set_piece, None
            self._take_set_piece(set_piece)
            return
        if self._apply_defensive_pressure():
            return
        match self._choose_action():
            case "shot":
                self._shoot(situation="open_play")
            case "carry":
                self._carry()
            case "dribble":
                self._dribble()
            case "pass":
                self._pass()
        self._transition_actions = max(0, self._transition_actions - 1)

    def _attacking_right(self, side: TeamSide) -> bool:
        return attacks_right(side, self._log.period)

    def _in_frame(self, spot: Spot, side: TeamSide) -> Spot:
        return to_attacking_frame(spot, attacking_right=self._attacking_right(side))

    def _from_frame(self, frame_spot: Spot, side: TeamSide) -> Spot:
        return from_attacking_frame(frame_spot, attacking_right=self._attacking_right(side))

    def _shape(self, side: TeamSide) -> dict[str, Spot]:
        return team_shape(
            self._teams[side],
            self._ball,
            attacking_right=self._attacking_right(side),
            in_possession=side == self._possession,
        )

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
        tuning = self._tuning
        side = self._possession
        passer = self._carrier
        origin = self._ball
        length = origin.distance_to(target)
        forward_gain = self._in_frame(target, side).x - self._in_frame(origin, side).x

        outcome: PassOutcome = "complete"
        end = target
        if self._rng.random() >= self._pass_success_probability(length, height, target):
            failure = self._rng.random()
            offside_possible = (
                forward_gain > 5 and self._in_frame(target, side).x > FINAL_THIRD_START_M
            )
            if offside_possible and failure < tuning.offside_share:
                outcome = "offside"
            elif failure < tuning.offside_share + tuning.out_of_play_share:
                outcome = "out"
                end = self._out_of_play_spot(target)
            else:
                outcome = "incomplete"
                end = origin.toward(target, self._rng.uniform(0.55, 1.0))

        event = self._log.emit(
            PassEvent,
            team_id=side,
            player_id=passer.player_id,
            location=to_point(origin),
            end_location=to_point(end),
            outcome=outcome,
            attrs=PassAttrs(
                receiver_id=receiver.player_id,
                length_m=round(length, 1),
                height=height,
                under_pressure=self._pressure >= tuning.pressured_threshold,
                ball_speed_kmh=self._ball_speed_kmh(length, height),
            ),
        )
        pass_ms = self._uniform_ms(tuning.pass_duration_ms) + int(
            length * tuning.pass_duration_per_m_ms
        )
        self._log.advance(min(pass_ms, tuning.max_pass_duration_ms))

        match outcome:
            case "complete":
                self._carrier = receiver
                self._ball = end
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
        frame_ball = self._in_frame(self._ball, side)
        pace_factor = 0.7 + 0.6 * self._carrier.player.traits.pace / 100
        if self._log.period == 2:
            pace_factor *= tuning.second_half_pace_factor
        distance = self._rng.uniform(tuning.carry_min_m, tuning.carry_max_m) * pace_factor
        if self._transition_actions > 0:
            distance *= 1 + tuning.transition_carry_boost
        heading = self._rng.gauss(0, tuning.carry_heading_sd_rad)
        if frame_ball.x > FINAL_THIRD_START_M:
            distance *= tuning.final_third_carry_factor
            heading += (CENTRE_LATERAL_M - frame_ball.y) / 120
        frame_end = Spot(
            min(frame_ball.x + distance * math.cos(heading), PITCH_LENGTH_M - 2.0),
            min(max(frame_ball.y + distance * math.sin(heading), 1.0), PITCH_WIDTH_M - 1.0),
        )
        end = self._from_frame(frame_end, side)
        travelled = self._ball.distance_to(end)
        self._log.emit(
            CarryEvent,
            team_id=side,
            player_id=self._carrier.player_id,
            location=to_point(self._ball),
            end_location=to_point(end),
            attrs=CarryAttrs(distance_m=round(travelled, 1)),
        )
        self._log.advance(
            tuning.carry_duration_base_ms + int(travelled * tuning.carry_duration_per_m_ms)
        )
        self._ball = end
        challenge_probability = (
            tuning.carry_challenge_base + tuning.carry_challenge_pressure_weight * self._pressure
        )
        if in_penalty_area(self._in_frame(end, side)):
            challenge_probability *= tuning.penalty_area_challenge_factor
        if self._rng.random() < challenge_probability:
            self._defensive_challenge()

    def _dribble(self) -> None:
        tuning = self._tuning
        side = self._possession
        defending_side = opponent(side)
        defender = self._nearest(defending_side, self._ball, outfield_only=True)
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
        self._ball = self._from_frame(
            Spot(min(frame_ball.x + gain, PITCH_LENGTH_M - 2.0), frame_ball.y), side
        )
        self._pressure = 0.0

    def _shoot(self, *, situation: ShotSituation, body_part: BodyPart | None = None) -> None:
        tuning = self._tuning
        side = self._possession
        defending_side = opponent(side)
        shooter = self._carrier
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
        outcome = self._shot_outcome(goal_probability, situation)
        assist = self._assist_pass if self._assisted_by_last_pass(shooter) else None
        end_spot = self._shot_end_spot(outcome)

        shot = self._log.emit(
            ShotEvent,
            team_id=side,
            player_id=shooter.player_id,
            location=to_point(origin),
            end_location=to_point(end_spot),
            outcome=outcome,
            attrs=ShotAttrs(
                body_part=body_part,
                shot_speed_kmh=self._shot_speed_kmh(body_part, shooter),
                situation=situation,
                assist_event_id=assist.event_id if assist else None,
            ),
        )
        self._log.advance(self._uniform_ms(tuning.shot_duration_ms))
        self._assist_pass = None

        match outcome:
            case "goal":
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
                if self._rng.random() < tuning.save_to_corner_share:
                    self._ball_out(defending_side, keeper, self._shot_end_spot("off_target"))
                else:
                    self._change_possession(
                        defending_side,
                        keeper,
                        self._goalkeeper_spot(defending_side),
                        transition=False,
                    )
            case "blocked":
                if self._rng.random() < tuning.block_to_corner_share:
                    blocker = self._nearest(defending_side, origin, outfield_only=True)
                    self._ball_out(defending_side, blocker, self._shot_end_spot("off_target"))
                else:
                    self._rebound(origin)
            case "off_target":
                self._ball_out(side, shooter, end_spot)
            case "woodwork":
                self._rebound(end_spot)

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
        self._log.advance(self._uniform_ms(bounds))
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
