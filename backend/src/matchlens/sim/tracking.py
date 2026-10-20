import math
from bisect import bisect_right
from dataclasses import dataclass
from random import Random

from matchlens.models.base import TeamSide
from matchlens.models.clock import MatchClock
from matchlens.models.events import (
    BallOutEvent,
    CardEvent,
    CarryEvent,
    DuelEvent,
    FoulEvent,
    InterceptionEvent,
    KickoffEvent,
    MatchEvent,
    PassEvent,
    PossessionChangeEvent,
    ShotEvent,
    SubstitutionEvent,
    TackleEvent,
)
from matchlens.models.match import MatchMetadata
from matchlens.models.pitch import PITCH_LENGTH_M, PITCH_WIDTH_M, Point
from matchlens.models.tracking import BallSample, PlayerPos, TrackingFrame
from matchlens.sim.shape import opponent_defensive_line, team_shape
from matchlens.sim.space import (
    CENTRE_SPOT,
    HALFWAY_M,
    Period,
    Spot,
    attacks_right,
    clamp_to_pitch,
    from_attacking_frame,
    to_attacking_frame,
)
from matchlens.sim.squad import PlayerState, TeamState

FRAME_INTERVAL_MS = 1_000
MS_PER_SECOND = 1_000
KMH_PER_MPS = 3.6
MAX_REPORTED_SPEED_KMH = 36.0
MOVEMENT_SPEED_LIMIT_KMH = 35.4
BASE_TOP_SPEED_KMH = 25.0
PACE_TOP_SPEED_KMH = 10.5
ACCELERATION_LIMIT_MPS2 = 3.0
SECOND_HALF_SPEED_FACTOR = 0.97
RESPONSE_PER_SECOND = 0.35
NOISE_PERSISTENCE = 0.85
NOISE_STEP_SD_M = 0.35
INVOLVEMENT_MS = 2_000
ANTICIPATION_MS = 3_000
PERSONAL_SPACE_M = 1.4
SUPPORT_RUN_MS = 4_500
COUNTER_WINDOW_MS = 6_000
COUNTER_SURGE_M = 12.0
COUNTER_RECOVERY_M = 8.0
CARRY_SPEED_MPS = 5.0
PASS_SPEED_RETENTION = 0.7
MIN_FLIGHT_MS = 300
KICKOFF_MAX_DEPTH_M = HALFWAY_M - 1.0
SUBSTITUTE_ENTRY_SPOT = Spot(HALFWAY_M, 0.0)
SIDES: tuple[TeamSide, TeamSide] = ("home", "away")
PERIODS: tuple[Period, Period] = (1, 2)


@dataclass(frozen=True, slots=True)
class Keyframe:
    ms: int
    spot: Spot


@dataclass(frozen=True, slots=True)
class FrameMoment:
    period: Period
    ms: int
    ball: Spot


@dataclass(frozen=True, slots=True)
class BallFlight:
    event: PassEvent | CarryEvent | ShotEvent
    arrival_ms: int
    apex_m: float


@dataclass(frozen=True, slots=True)
class BallHold:
    start_ms: int
    end_ms: int
    spot: Spot


class BallTrack:
    def __init__(
        self,
        keyframes: dict[Period, list[Keyframe]],
        flights: dict[Period, list[BallFlight]],
        holds: dict[Period, list[BallHold]],
    ) -> None:
        self._keyframes = keyframes
        self._times = {
            period: [frame.ms for frame in frames] for period, frames in keyframes.items()
        }
        self._flights = flights
        self._flight_times = {
            period: [flight.event.clock.ms for flight in items] for period, items in flights.items()
        }
        self._holds = holds
        self._hold_times = {
            period: [hold.start_ms for hold in items] for period, items in holds.items()
        }

    @classmethod
    def from_events(cls, events: list[MatchEvent]) -> "BallTrack":
        keyframes: dict[Period, list[Keyframe]] = {1: [], 2: []}
        flights: dict[Period, list[BallFlight]] = {1: [], 2: []}
        holds: dict[Period, list[BallHold]] = {1: [], 2: []}
        located = [(event, event.location) for event in events if event.location is not None]
        for index, (event, location) in enumerate(located):
            period = event.clock.period
            start = spot_of(location)
            keyframes[period].append(Keyframe(event.clock.ms, start))
            following = located[index + 1][0] if index + 1 < len(located) else None
            following_ms = (
                following.clock.ms
                if following is not None and following.clock.period == period
                else event.clock.ms
            )
            if isinstance(event, BallOutEvent | FoulEvent) and following_ms > event.clock.ms:
                holds[period].append(BallHold(event.clock.ms, following_ms, start))
            if event.end_location is None:
                continue
            end = spot_of(event.end_location)
            arrival_ms = event.clock.ms + _flight_ms(event, start.distance_to(end))
            if following is not None and following.clock.period == period:
                arrival_ms = min(arrival_ms, following.clock.ms)
            keyframes[period].append(Keyframe(arrival_ms, end))
            flights[period].append(BallFlight(event, arrival_ms, _flight_apex(event, start, end)))
            dead_ball = (isinstance(event, ShotEvent) and event.outcome == "goal") or (
                isinstance(event, PassEvent) and event.outcome == "offside"
            )
            if dead_ball and following_ms > arrival_ms:
                holds[period].append(BallHold(arrival_ms, following_ms, end))
        return cls(keyframes, flights, holds)

    def position(self, period: Period, ms: int) -> Spot:
        hold_index = bisect_right(self._hold_times[period], ms) - 1
        if hold_index >= 0:
            hold = self._holds[period][hold_index]
            if ms < hold.end_ms:
                return hold.spot
        frames = self._keyframes[period]
        if not frames:
            return CENTRE_SPOT
        index = bisect_right(self._times[period], ms)
        if index == 0:
            return frames[0].spot
        if index == len(frames):
            return frames[-1].spot
        before, after = frames[index - 1], frames[index]
        if after.ms == before.ms:
            return after.spot
        return before.spot.toward(after.spot, (ms - before.ms) / (after.ms - before.ms))

    def restarted(self, period: Period, start_ms: int, end_ms: int) -> bool:
        begin = max(0, bisect_right(self._hold_times[period], start_ms) - 1)
        end = bisect_right(self._hold_times[period], end_ms)
        return any(start_ms < hold.end_ms <= end_ms for hold in self._holds[period][begin:end])

    def flight_at(self, period: Period, ms: int) -> BallFlight | None:
        index = bisect_right(self._flight_times[period], ms) - 1
        if index < 0:
            return None
        flight = self._flights[period][index]
        return flight if ms <= flight.arrival_ms else None

    def trajectory(self, period: Period, ms: int) -> list[BallSample]:
        if ms == 0:
            return []
        start = max(0, ms - FRAME_INTERVAL_MS)
        times = {start, ms, *range(start, ms, 250)}
        # Include exact contacts and arrivals; even a short pass between two
        # 1 Hz frames must be visible with its actual synthetic flight timing.
        begin = bisect_right(self._times[period], start)
        end = bisect_right(self._times[period], ms)
        times.update(self._times[period][begin:end])
        hold_begin = max(0, bisect_right(self._hold_times[period], start) - 1)
        hold_end = bisect_right(self._hold_times[period], ms)
        for hold in self._holds[period][hold_begin:hold_end]:
            if start < hold.end_ms <= ms:
                times.update((hold.end_ms - 1, hold.end_ms))
        return [self._sample(period, time, time - start) for time in sorted(times)]

    def _sample(self, period: Period, ms: int, offset_ms: int) -> BallSample:
        spot = self.position(period, ms)
        base = BallSample(offset_ms=offset_ms, x=round(spot.x, 3), y=round(spot.y, 3), height_m=0)
        flight = self.flight_at(period, ms)
        if flight is None:
            return base
        duration = flight.arrival_ms - flight.event.clock.ms
        if duration <= 0:
            return base
        progress = min(1.0, max(0.0, (ms - flight.event.clock.ms) / duration))
        # Height belongs to the synthetic feed, not an inference in the UI.
        return BallSample(
            offset_ms=offset_ms,
            x=base.x,
            y=base.y,
            height_m=round(4 * flight.apex_m * progress * (1 - progress), 3),
            action=(
                "pass"
                if isinstance(flight.event, PassEvent)
                else "shot"
                if isinstance(flight.event, ShotEvent)
                else "carry"
            ),
            actor_id=flight.event.player_id,
            event_id=flight.event.event_id,
            progress=round(progress, 4),
        )


def spot_of(point: Point) -> Spot:
    return Spot(point.x, point.y)


def _flight_apex(event: PassEvent | CarryEvent | ShotEvent, start: Spot, end: Spot) -> float:
    if isinstance(event, PassEvent):
        if event.attrs.height == "high":
            return min(7.0, 1.4 + start.distance_to(end) * 0.1)
        return 0.45 if event.attrs.height == "low" else 0.0
    if isinstance(event, ShotEvent):
        return 0.7 if event.attrs.body_part == "head" else 0.45
    return 0.0


def _flight_ms(event: MatchEvent, distance_m: float) -> int:
    if isinstance(event, PassEvent):
        speed_mps = event.attrs.ball_speed_kmh / KMH_PER_MPS * PASS_SPEED_RETENTION
    elif isinstance(event, ShotEvent):
        speed_mps = event.attrs.shot_speed_kmh / KMH_PER_MPS
    elif isinstance(event, CarryEvent):
        speed_mps = CARRY_SPEED_MPS
    else:
        return MIN_FLIGHT_MS
    return max(MIN_FLIGHT_MS, round(distance_m / speed_mps * MS_PER_SECOND))


class TrackingBuilder:
    def __init__(self, metadata: MatchMetadata, events: list[MatchEvent], rng: Random) -> None:
        self._match_id = metadata.match_id
        self._events = events
        self._rng = rng
        self._ball_track = BallTrack.from_events(events)
        self._teams: dict[TeamSide, TeamState] = {
            "home": TeamState.from_team(metadata.home),
            "away": TeamState.from_team(metadata.away),
        }
        self._positions: dict[str, Spot] = {}
        self._reported: dict[str, Spot] = {}
        self._velocities: dict[str, Spot] = {}
        self._noise: dict[str, Spot] = {}
        self._focus: dict[str, Keyframe] = {}
        self._possession: TeamSide = "home"
        self._carrier_id: str | None = None
        self._counter_side: TeamSide | None = None
        self._counter_until_ms = 0
        self._previous_event: MatchEvent | None = None
        self._previous_ball: Spot | None = None
        # The synthetic simulator knows its event script. Let participants move
        # towards their next involvement before the action, rather than chasing
        # a pass location only after the ball has already left it.
        self._actions: dict[tuple[Period, str], list[Keyframe]] = {}
        for event in events:
            if event.player_id is not None and event.location is not None:
                self._actions.setdefault((event.clock.period, event.player_id), []).append(
                    Keyframe(event.clock.ms, spot_of(event.location))
                )
            if isinstance(event, PassEvent) and event.outcome == "complete":
                arrival = event.clock.ms + _flight_ms(
                    event, spot_of(event.location).distance_to(spot_of(event.end_location))
                )
                self._actions.setdefault((event.clock.period, event.attrs.receiver_id), []).append(
                    Keyframe(arrival, spot_of(event.end_location))
                )
        for actions in self._actions.values():
            actions.sort(key=lambda action: action.ms)
        self._action_times = {
            key: [action.ms for action in actions] for key, actions in self._actions.items()
        }
        self._frame_positions: dict[str, Spot] = {}

    def build(self) -> list[TrackingFrame]:
        frames: list[TrackingFrame] = []
        cursor = 0
        for period in PERIODS:
            period_end_ms = max(
                event.clock.ms for event in self._events if event.clock.period == period
            )
            self._line_up_for_kickoff(period)
            for ms in range(0, period_end_ms + 1, FRAME_INTERVAL_MS):
                while cursor < len(self._events) and _at_or_before(
                    self._events[cursor], period, ms
                ):
                    self._apply(self._events[cursor])
                    cursor += 1
                frames.append(self._frame(period, ms, frame_seq=len(frames) + 1))
        return frames

    def _line_up_for_kickoff(self, period: Period) -> None:
        self._positions.clear()
        self._reported.clear()
        self._velocities.clear()
        self._focus.clear()
        self._previous_ball = None
        self._counter_side = None
        for side in SIDES:
            attacking_right = attacks_right(side, period)
            shape = team_shape(
                self._teams[side], CENTRE_SPOT, attacking_right=attacking_right, in_possession=False
            )
            for player_id, spot in shape.items():
                frame_spot = to_attacking_frame(spot, attacking_right=attacking_right)
                own_half = Spot(min(frame_spot.x, KICKOFF_MAX_DEPTH_M), frame_spot.y)
                self._positions[player_id] = from_attacking_frame(
                    own_half, attacking_right=attacking_right
                )
                self._noise.setdefault(player_id, Spot(0.0, 0.0))

    def _apply(self, event: MatchEvent) -> None:
        ms = event.clock.ms
        if isinstance(event, KickoffEvent):
            self._possession = event.team_id
            self._carrier_id = event.player_id
        elif isinstance(event, PossessionChangeEvent):
            self._possession = event.team_id
            self._carrier_id = None
            if self._won_in_open_play(self._previous_event):
                self._counter_side = event.team_id
                self._counter_until_ms = ms + COUNTER_WINDOW_MS
        elif isinstance(event, SubstitutionEvent):
            team = self._teams[event.team_id]
            player_out = team.player(event.attrs.player_out_id)
            team.substitute(team.player(event.attrs.player_in_id), player_out)
            self._forget(player_out.player_id)
            self._positions[event.attrs.player_in_id] = SUBSTITUTE_ENTRY_SPOT
            self._noise[event.attrs.player_in_id] = Spot(0.0, 0.0)
        elif isinstance(event, CardEvent) and event.outcome in ("red", "second_yellow"):
            self._teams[event.team_id].player(event.player_id).sent_off = True
            self._forget(event.player_id)

        if isinstance(event, PassEvent):
            self._carrier_id = event.attrs.receiver_id if event.outcome == "complete" else None
            self._focus[event.player_id] = Keyframe(ms + 700, spot_of(event.location))
            self._focus[event.attrs.receiver_id] = Keyframe(
                ms + INVOLVEMENT_MS, spot_of(event.end_location)
            )
            if event.outcome == "complete":
                self._start_support_run(event)
        elif event.player_id is not None and event.location is not None:
            if event.team_id == self._possession:
                self._carrier_id = event.player_id
            destination = event.end_location if event.end_location is not None else event.location
            self._focus[event.player_id] = Keyframe(ms + INVOLVEMENT_MS, spot_of(destination))
        self._previous_event = event

    def _start_support_run(self, event: PassEvent) -> None:
        if self._rng.random() >= 0.28:
            return
        side = event.team_id
        attacking_right = attacks_right(side, event.clock.period)
        ball = spot_of(event.end_location)
        ball_frame = to_attacking_frame(ball, attacking_right=attacking_right)
        if ball_frame.x >= PITCH_LENGTH_M - 20.0:
            return
        team = self._teams[side]
        candidates = [
            player
            for player in team.outfield()
            if player.player_id not in {event.player_id, event.attrs.receiver_id}
            and player.player.role in {"W", "AM", "ST"}
        ]
        if not candidates:
            return
        runner = self._rng.choice(candidates)
        shape = team_shape(team, ball, attacking_right=attacking_right, in_possession=True)
        runner_frame = to_attacking_frame(shape[runner.player_id], attacking_right=attacking_right)
        onside_limit = opponent_defensive_line(ball_frame.x) - 1.5
        available_run = min(onside_limit, PITCH_LENGTH_M - 2.0) - runner_frame.x
        if available_run < 2.5:
            return
        run_depth = min(self._rng.uniform(4.0, 8.0), available_run)
        lateral_shift = self._rng.uniform(-2.0, 2.0)
        target = Spot(
            runner_frame.x + run_depth,
            min(max(runner_frame.y + lateral_shift, 2.0), PITCH_WIDTH_M - 2.0),
        )
        self._focus[runner.player_id] = Keyframe(
            event.clock.ms + SUPPORT_RUN_MS,
            from_attacking_frame(target, attacking_right=attacking_right),
        )

    def _forget(self, player_id: str) -> None:
        self._positions.pop(player_id, None)
        self._reported.pop(player_id, None)
        self._velocities.pop(player_id, None)

    @staticmethod
    def _won_in_open_play(event: MatchEvent | None) -> bool:
        if isinstance(event, InterceptionEvent):
            return True
        if isinstance(event, TackleEvent):
            return event.outcome == "won"
        if isinstance(event, DuelEvent):
            return event.outcome == "lost"
        return False

    def _frame(self, period: Period, ms: int, *, frame_seq: int) -> TrackingFrame:
        ball = self._ball_track.position(period, ms)
        moment = FrameMoment(period=period, ms=ms, ball=ball)
        players: list[PlayerPos] = []
        # All players react to the same state, independent of iteration order.
        self._frame_positions = dict(self._positions)
        for side in SIDES:
            team = self._teams[side]
            shape = team_shape(
                team,
                ball,
                attacking_right=attacks_right(side, period),
                in_possession=side == self._possession,
            )
            for player in team.on_pitch():
                target = self._target(player, side, shape[player.player_id], moment)
                key = (period, player.player_id)
                next_action = bisect_right(self._action_times.get(key, []), ms)
                actions = self._actions.get(key, [])
                involved = player.player_id == self._carrier_id or (
                    next_action < len(actions) and actions[next_action].ms - ms <= ANTICIPATION_MS
                )
                players.append(self._move(player, target, period, involved=involved))
        restarted = self._ball_track.restarted(period, ms - FRAME_INTERVAL_MS, ms)
        ball_speed = (
            0.0
            if self._previous_ball is None or restarted
            else _speed_kmh(self._previous_ball, ball)
        )
        self._previous_ball = _rounded(ball)
        return TrackingFrame(
            match_id=self._match_id,
            frame_seq=frame_seq,
            clock=MatchClock(period=period, ms=ms),
            ball=_point(ball),
            ball_speed_kmh=round(ball_speed, 1),
            players=players,
            ball_trajectory=self._ball_track.trajectory(period, ms),
        )

    def _target(
        self, player: PlayerState, side: TeamSide, shape_spot: Spot, moment: FrameMoment
    ) -> Spot:
        involvement = self._involvement_target(player, side, shape_spot, moment)
        if involvement is not None:
            return involvement
        key = (moment.period, player.player_id)
        actions = self._actions.get(key, [])
        index = bisect_right(self._action_times.get(key, []), moment.ms)
        if index < len(actions) and 0 < actions[index].ms - moment.ms <= ANTICIPATION_MS:
            return actions[index].spot
        focus = self._focus.get(player.player_id)
        if focus is not None and moment.ms <= focus.ms:
            return focus.spot
        if side == self._possession and player.player_id == self._carrier_id:
            return moment.ball
        target = shape_spot
        attacking_right = attacks_right(side, moment.period)
        if (
            self._counter_side is not None
            and moment.ms <= self._counter_until_ms
            and not player.is_goalkeeper
        ):
            shift = COUNTER_SURGE_M if side == self._counter_side else -COUNTER_RECOVERY_M
            frame_spot = to_attacking_frame(target, attacking_right=attacking_right)
            surged = Spot(min(max(frame_spot.x + shift, 1.0), PITCH_LENGTH_M - 2.0), frame_spot.y)
            target = from_attacking_frame(surged, attacking_right=attacking_right)
        noise = self._next_noise(player.player_id)
        spacing = self._spacing(player.player_id) if not player.is_goalkeeper else Spot(0.0, 0.0)
        return clamp_to_pitch(Spot(target.x + noise.x + spacing.x, target.y + noise.y + spacing.y))

    def _involvement_target(
        self, player: PlayerState, side: TeamSide, shape_spot: Spot, moment: FrameMoment
    ) -> Spot | None:
        flight = self._ball_track.flight_at(moment.period, moment.ms)
        if flight is not None:
            event = flight.event
            if isinstance(event, CarryEvent) and event.player_id == player.player_id:
                return self._ball_track.position(
                    moment.period, min(moment.ms + 350, flight.arrival_ms)
                )
            if isinstance(event, PassEvent) and event.attrs.receiver_id == player.player_id:
                return spot_of(event.end_location)
            if (
                isinstance(event, ShotEvent)
                and event.end_location is not None
                and player.is_goalkeeper
                and event.team_id != side
            ):
                end = spot_of(event.end_location)
                return Spot(end.x * 0.95 + shape_spot.x * 0.05, min(38.0, max(30.0, end.y)))
        return None

    def _spacing(self, player_id: str) -> Spot:
        current = self._frame_positions.get(player_id)
        if current is None:
            return Spot(0.0, 0.0)
        x, y = 0.0, 0.0
        for other_id, other in self._frame_positions.items():
            if other_id == player_id:
                continue
            distance = current.distance_to(other)
            if distance >= PERSONAL_SPACE_M:
                continue
            if distance < 0.01:
                x += 0.7 if player_id > other_id else -0.7
                continue
            strength = (PERSONAL_SPACE_M - distance) / PERSONAL_SPACE_M
            x += (current.x - other.x) / distance * strength
            y += (current.y - other.y) / distance * strength
        return Spot(x, y)

    def _next_noise(self, player_id: str) -> Spot:
        previous = self._noise.get(player_id, Spot(0.0, 0.0))
        noise = Spot(
            previous.x * NOISE_PERSISTENCE + self._rng.gauss(0, NOISE_STEP_SD_M),
            previous.y * NOISE_PERSISTENCE + self._rng.gauss(0, NOISE_STEP_SD_M),
        )
        self._noise[player_id] = noise
        return noise

    def _move(
        self, player: PlayerState, target: Spot, period: Period, *, involved: bool = False
    ) -> PlayerPos:
        player_id = player.player_id
        current = self._positions.get(player_id, target)
        gap = current.distance_to(target)
        top_speed_kmh = min(
            BASE_TOP_SPEED_KMH + PACE_TOP_SPEED_KMH * player.player.traits.pace / 100,
            MOVEMENT_SPEED_LIMIT_KMH,
        )
        if period == 2:
            top_speed_kmh *= SECOND_HALF_SPEED_FACTOR
        response = 0.65 if involved else RESPONSE_PER_SECOND
        desired_speed = min(gap * response, top_speed_kmh / KMH_PER_MPS)
        desired = (
            Spot(0.0, 0.0)
            if gap == 0
            else Spot(
                (target.x - current.x) / gap * desired_speed,
                (target.y - current.y) / gap * desired_speed,
            )
        )
        velocity = _accelerate(self._velocities.get(player_id, Spot(0.0, 0.0)), desired)
        moved = clamp_to_pitch(Spot(current.x + velocity.x, current.y + velocity.y))
        self._velocities[player_id] = Spot(moved.x - current.x, moved.y - current.y)
        self._positions[player_id] = moved

        reported = _rounded(moved)
        previous = self._reported.get(player_id)
        speed = (
            0.0 if previous is None else min(_speed_kmh(previous, reported), MAX_REPORTED_SPEED_KMH)
        )
        self._reported[player_id] = reported
        return PlayerPos(player_id=player_id, x=reported.x, y=reported.y, speed_kmh=round(speed, 1))


def _accelerate(velocity: Spot, desired: Spot) -> Spot:
    change = Spot(desired.x - velocity.x, desired.y - velocity.y)
    magnitude = math.hypot(change.x, change.y)
    if magnitude <= ACCELERATION_LIMIT_MPS2:
        return desired
    scale = ACCELERATION_LIMIT_MPS2 / magnitude
    return Spot(velocity.x + change.x * scale, velocity.y + change.y * scale)


def _at_or_before(event: MatchEvent, period: Period, ms: int) -> bool:
    return (event.clock.period, event.clock.ms) <= (period, ms)


def _rounded(spot: Spot) -> Spot:
    clamped = clamp_to_pitch(spot)
    return Spot(round(clamped.x, 1), round(clamped.y, 1))


def _point(spot: Spot) -> Point:
    rounded = _rounded(spot)
    return Point(x=rounded.x, y=rounded.y)


def _speed_kmh(previous: Spot, current: Spot) -> float:
    seconds = FRAME_INTERVAL_MS / MS_PER_SECOND
    return math.hypot(current.x - previous.x, current.y - previous.y) / seconds * KMH_PER_MPS


def build_tracking_frames(
    metadata: MatchMetadata, events: list[MatchEvent], rng: Random
) -> list[TrackingFrame]:
    return TrackingBuilder(metadata, events, rng).build()
