import math
from bisect import bisect_right
from dataclasses import dataclass
from random import Random

from matchlens.models.base import TeamSide
from matchlens.models.clock import MatchClock
from matchlens.models.events import (
    CardEvent,
    CarryEvent,
    DuelEvent,
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
from matchlens.models.pitch import PITCH_LENGTH_M, Point
from matchlens.models.tracking import PlayerPos, TrackingFrame
from matchlens.sim.shape import team_shape
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


class BallTrack:
    def __init__(self, keyframes: dict[Period, list[Keyframe]]) -> None:
        self._keyframes = keyframes
        self._times = {
            period: [frame.ms for frame in frames] for period, frames in keyframes.items()
        }

    @classmethod
    def from_events(cls, events: list[MatchEvent]) -> "BallTrack":
        keyframes: dict[Period, list[Keyframe]] = {1: [], 2: []}
        located = [(event, event.location) for event in events if event.location is not None]
        for index, (event, location) in enumerate(located):
            period = event.clock.period
            start = spot_of(location)
            keyframes[period].append(Keyframe(event.clock.ms, start))
            if event.end_location is None:
                continue
            end = spot_of(event.end_location)
            arrival_ms = event.clock.ms + _flight_ms(event, start.distance_to(end))
            following = located[index + 1][0] if index + 1 < len(located) else None
            if following is not None and following.clock.period == period:
                arrival_ms = min(arrival_ms, following.clock.ms)
            keyframes[period].append(Keyframe(arrival_ms, end))
        return cls(keyframes)

    def position(self, period: Period, ms: int) -> Spot:
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


def spot_of(point: Point) -> Spot:
    return Spot(point.x, point.y)


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
            self._focus[event.player_id] = Keyframe(ms + INVOLVEMENT_MS, spot_of(event.location))
            self._focus[event.attrs.receiver_id] = Keyframe(
                ms + INVOLVEMENT_MS, spot_of(event.end_location)
            )
        elif event.player_id is not None and event.location is not None:
            if event.team_id == self._possession:
                self._carrier_id = event.player_id
            destination = event.end_location if event.end_location is not None else event.location
            self._focus[event.player_id] = Keyframe(ms + INVOLVEMENT_MS, spot_of(destination))
        self._previous_event = event

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
                players.append(self._move(player, target, period))
        ball_speed = 0.0 if self._previous_ball is None else _speed_kmh(self._previous_ball, ball)
        self._previous_ball = _rounded(ball)
        return TrackingFrame(
            match_id=self._match_id,
            frame_seq=frame_seq,
            clock=MatchClock(period=period, ms=ms),
            ball=_point(ball),
            ball_speed_kmh=round(ball_speed, 1),
            players=players,
        )

    def _target(
        self, player: PlayerState, side: TeamSide, shape_spot: Spot, moment: FrameMoment
    ) -> Spot:
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
        return clamp_to_pitch(Spot(target.x + noise.x, target.y + noise.y))

    def _next_noise(self, player_id: str) -> Spot:
        previous = self._noise.get(player_id, Spot(0.0, 0.0))
        noise = Spot(
            previous.x * NOISE_PERSISTENCE + self._rng.gauss(0, NOISE_STEP_SD_M),
            previous.y * NOISE_PERSISTENCE + self._rng.gauss(0, NOISE_STEP_SD_M),
        )
        self._noise[player_id] = noise
        return noise

    def _move(self, player: PlayerState, target: Spot, period: Period) -> PlayerPos:
        player_id = player.player_id
        current = self._positions.get(player_id, target)
        gap = current.distance_to(target)
        top_speed_kmh = min(
            BASE_TOP_SPEED_KMH + PACE_TOP_SPEED_KMH * player.player.traits.pace / 100,
            MOVEMENT_SPEED_LIMIT_KMH,
        )
        if period == 2:
            top_speed_kmh *= SECOND_HALF_SPEED_FACTOR
        desired_speed = min(gap * RESPONSE_PER_SECOND, top_speed_kmh / KMH_PER_MPS)
        desired = (
            Spot(0.0, 0.0)
            if gap == 0
            else Spot(
                (target.x - current.x) / gap * desired_speed,
                (target.y - current.y) / gap * desired_speed,
            )
        )
        velocity = _accelerate(self._velocities.get(player_id, Spot(0.0, 0.0)), desired)
        self._velocities[player_id] = velocity
        moved = Spot(current.x + velocity.x, current.y + velocity.y)
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
