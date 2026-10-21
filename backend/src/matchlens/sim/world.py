"""Shared, deterministic movement and contact state for the match engine.

The match director chooses intentions. This world resolves their movement;
events and recorded playback both read the resulting state.
"""

import math
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from matchlens.models.base import TeamSide
from matchlens.models.clock import MatchClock
from matchlens.models.pitch import Point
from matchlens.models.tracking import BallSample, PlayerPos, TrackingFrame
from matchlens.sim.shape import team_shape
from matchlens.sim.space import (
    CENTRE_SPOT,
    Period,
    Spot,
    attacks_right,
    clamp_to_pitch,
    from_attacking_frame,
    opponent,
    to_attacking_frame,
)
from matchlens.sim.squad import TeamState

STEP_MS = 50
GRAVITY = 9.81
ROLL_DECELERATION = 1.8
PLAYER_RADIUS = 0.43
BALL_RADIUS = 0.25
BODY_GAP = PLAYER_RADIUS * 2 + 0.004
BALL_BODY_GAP = PLAYER_RADIUS + BALL_RADIUS + 0.004
BODY_HEIGHT = 2.15
CONTROL_OFFSET = BALL_BODY_GAP + 0.08


@dataclass(slots=True)
class Body:
    spot: Spot
    velocity: Spot
    heading: float


@dataclass(slots=True)
class Flight:
    actor_id: str
    side: TeamSide
    receiver_id: str | None
    action: Literal["pass", "shot"]
    origin: Spot
    target: Spot
    speed: float
    velocity: Spot
    vertical_speed: float
    started_ms: int
    travelled: float = 0.0


@dataclass(frozen=True, slots=True)
class Contact:
    outcome: Literal[
        "complete", "intercepted", "blocked", "saved", "goal", "out", "loose", "woodwork"
    ]
    spot: Spot
    player_id: str | None = None


class MatchWorld:
    def __init__(self, match_id: str, teams: dict[TeamSide, TeamState], *, record: bool) -> None:
        self.match_id = match_id
        self.teams = teams
        self.record = record
        self.period: Period = 1
        self.ms = 0
        self.ball = CENTRE_SPOT
        self.height: float = 0.0
        self.owner_id: str | None = None
        self.side: TeamSide = "home"
        self.controlled = False
        self.dead_ball = False
        self.resetting = False
        self.carry_target: Spot | None = None
        self.receive_target: tuple[str, Spot] | None = None
        self.restart_side: TeamSide | None = None
        self.face_target: Spot | None = None
        self.flight: Flight | None = None
        self.contact: Contact | None = None
        self.preparing: Literal["pass", "shot"] | None = None
        self._preparation_ms = 0
        self._last_contact: tuple[int, Contact] | None = None
        self.bodies: dict[str, Body] = {}
        self.frames: list[TrackingFrame] = []
        self._targets: dict[str, Spot] = {}
        self._next_targets = 0
        self._samples: list[BallSample] = []
        self._paths: dict[str, list[tuple[int, float, float, float]]] = {}
        self._next_frame = 0
        self._frame_start_ms = 0
        self._previous_ball = CENTRE_SPOT
        self._placed_since_frame = False
        self._settle_speed: float = 0.0
        self._body_steps: list[tuple[float, dict[str, Spot]]] = []

    def start_period(self, period: Period) -> None:
        self.period, self.ms = period, 0
        self.flight, self.contact = None, None
        self.preparing = None
        self._last_contact = None
        self.carry_target = self.face_target = None
        self.receive_target = None
        self.restart_side = None
        self.controlled = False
        self.dead_ball = self.resetting = False
        self._settle_speed = 0.0
        self.bodies.clear()
        for side, team in self.teams.items():
            right = attacks_right(side, period)
            shape = team_shape(team, CENTRE_SPOT, attacking_right=right, in_possession=False)
            for player_id, spot in shape.items():
                local = to_attacking_frame(spot, attacking_right=right)
                self.bodies[player_id] = Body(
                    from_attacking_frame(Spot(min(51.0, local.x), local.y), attacking_right=right),
                    Spot(0.0, 0.0),
                    math.pi / 2 if right else -math.pi / 2,
                )
        self._samples, self._paths = [], {}
        self._next_frame, self._next_targets = 0, 0
        self._frame_start_ms = 0
        self._separate(0.0)

    def positions(self, side: TeamSide) -> dict[str, Spot]:
        self.sync_roster()
        return {
            player.player_id: self.bodies[player.player_id].spot
            for player in self.teams[side].on_pitch()
            if player.player_id in self.bodies
        }

    def sync_roster(self) -> None:
        active = {player.player_id for team in self.teams.values() for player in team.on_pitch()}
        if active == self.bodies.keys():
            return
        self.bodies = {key: body for key, body in self.bodies.items() if key in active}
        for player_id in sorted(active - self.bodies.keys()):
            self.bodies[player_id] = Body(Spot(52.5, 0.0), Spot(0.0, 0.0), 0.0)
        self._separate(0.0)
        self.invalidate_targets()

    def place(self, spot: Spot) -> None:
        changed = self.ball.distance_to(spot) > 0.01
        if self.record and self._samples and self.ms > self._frame_start_ms and changed:
            self._sample_ball(max(0, self.ms - self._frame_start_ms - 1))
        self._placed_since_frame |= self.ball.distance_to(spot) > 1.0
        self.ball, self.height = clamp_to_pitch(spot), 0.0
        self.flight, self.contact = None, None
        self.controlled = False
        self.carry_target = self.face_target = None
        # Explicit restart placement: retain both sides of the discontinuity.
        if self.record and self._samples and self.ms > self._frame_start_ms and changed:
            self._sample_ball(self.ms - self._frame_start_ms)
        elif (
            changed
            and self.record
            and self.frames
            and self.frames[-1].clock == MatchClock(period=self.period, ms=self.ms)
        ):
            last = self.frames[-1]
            offset = last.interval_ms
            old_path = [
                sample for sample in last.ball_trajectory if sample.offset_ms < max(0, offset - 1)
            ]
            if last.ball_trajectory:
                old_path.append(
                    last.ball_trajectory[-1].model_copy(update={"offset_ms": max(0, offset - 1)})
                )
            old_path.append(BallSample(offset_ms=offset, x=self.ball.x, y=self.ball.y, height_m=0))
            self.frames[-1] = last.model_copy(
                update={
                    "ball": Point(x=round(self.ball.x, 3), y=round(self.ball.y, 3)),
                    "ball_speed_kmh": 0.0,
                    "ball_trajectory": old_path,
                }
            )
            self._samples = []
            self._sample_ball(0)

    def invalidate_targets(self) -> None:
        self._next_targets = 0

    def prepare(self, action: Literal["pass", "shot"]) -> None:
        self.preparing, self._preparation_ms = action, self.ms

    def kickoff(self, player_id: str, side: TeamSide) -> None:
        self.owner_id, self.side = player_id, side
        self.place(CENTRE_SPOT)
        self.dead_ball, self.resetting = False, False
        self.restart_side = side
        self.invalidate_targets()
        if self.ms == 0:
            for player in self.teams[opponent(side)].on_pitch():
                body = self.bodies[player.player_id]
                gap = body.spot.distance_to(CENTRE_SPOT)
                if gap < 9.3:
                    right = attacks_right(opponent(side), self.period)
                    local = to_attacking_frame(body.spot, attacking_right=right)
                    body.spot = from_attacking_frame(
                        Spot(min(local.x, 43.0), local.y), attacking_right=right
                    )
            for _ in range(4):
                self._separate(0.2)
            heading = self.bodies[player_id].heading
            self.bodies[player_id].spot = Spot(
                52.5 - math.sin(heading) * CONTROL_OFFSET,
                34.0 - math.cos(heading) * CONTROL_OFFSET,
            )
            self.bodies[player_id].velocity = Spot(0.0, 0.0)
            self.controlled = True
            self._record_initial()

    def ready(self, target: Spot | None = None) -> bool:
        body = self.bodies.get(self.owner_id or "")
        if body is None or not self.controlled:
            return False
        if self.restart_side is not None and any(
            self.bodies[player.player_id].spot.distance_to(self.ball) < 9.0
            for player in self.teams[opponent(self.restart_side)].on_pitch()
        ):
            return False
        if target is None:
            return True
        desired = math.atan2(target.x - body.spot.x, target.y - body.spot.y)
        return abs(_angle(desired - body.heading)) < 0.18

    def launch(  # noqa: PLR0913 - explicit physical launch parameters
        self,
        target: Spot,
        *,
        action: Literal["pass", "shot"],
        receiver_id: str | None = None,
        apex: float = 0.0,
        speed: float = 20.0,
        target_height: float = 0.8,
    ) -> Flight:
        distance = max(0.1, self.ball.distance_to(target))
        if action == "pass" and apex == 0:
            speed = min(24.0, math.sqrt(5.0**2 + 2 * ROLL_DECELERATION * distance))
            vertical = 0.0
        elif action == "pass":
            vertical = math.sqrt(2 * GRAVITY * apex)
            speed = distance / max(0.3, 2 * vertical / GRAVITY)
        else:
            seconds = distance / max(1.0, speed)
            vertical = (target_height - self.height) / seconds + GRAVITY * seconds / 2
        velocity = Spot(
            (target.x - self.ball.x) / distance * speed,
            (target.y - self.ball.y) / distance * speed,
        )
        flight = Flight(
            self.owner_id or "",
            self.side,
            receiver_id,
            action,
            self.ball,
            target,
            speed,
            velocity,
            vertical,
            self.ms,
        )
        self.flight, self.contact, self.controlled = flight, None, False
        self.receive_target = None
        self.restart_side = None
        self.preparing = None
        self._last_contact = None
        self.carry_target = self.face_target = None
        self._next_targets = 0
        if self.record:
            self._sample_ball(self.ms - self._frame_start_ms)
            self._sample_players(self.ms - self._frame_start_ms)
            if self.ms > self._frame_start_ms:
                self._write_frame()
        return flight

    def finish_flight(self) -> None:
        if self.contact is not None:
            self._last_contact = self.ms, self.contact
        self.flight, self.contact = None, None
        self.controlled = False
        self._next_targets = 0

    def advance(self, period: Period, start_ms: int, duration_ms: int) -> None:
        if period != self.period:
            raise ValueError("world period was not initialized")
        end = start_ms + duration_ms
        while self.ms < end:
            step = min(STEP_MS, end - self.ms, 250 - self.ms % 250)
            if self.record and self._next_frame > self.ms:
                step = min(step, self._next_frame - self.ms)
            old = {key: body.spot for key, body in self.bodies.items()}
            self._move_players(step / 1000)
            if self.flight is not None and self.contact is None:
                self._move_ball(step / 1000, old)
            elif not self.dead_ball and self.contact is None:
                self._control_ball(step / 1000, old)
            elif self.dead_ball and self.height > 0:
                dt = step / 1000
                self.height = max(
                    0.0, self.height + self._settle_speed * dt - GRAVITY * dt * dt / 2
                )
                self._settle_speed = self._settle_speed - GRAVITY * dt if self.height > 0 else 0.0
            if self.record:
                for fraction, positions in self._body_steps:
                    offset = self.ms - self._frame_start_ms + round(fraction * step)
                    self._sample_players(offset, positions)
            self.ms += step
            if self.record:
                self._capture()

    def _refresh_targets(self) -> None:
        self.sync_roster()
        self._targets.clear()
        shape_ball = CENTRE_SPOT if self.resetting else self.ball
        for side, team in self.teams.items():
            shape = team_shape(
                team,
                shape_ball,
                attacking_right=attacks_right(side, self.period),
                in_possession=side == self.side and not self.dead_ball,
            )
            for player in team.on_pitch():
                if player.player_id not in self.bodies:
                    self.bodies[player.player_id] = Body(Spot(52.5, 0.0), Spot(0.0, 0.0), 0.0)
                self._targets[player.player_id] = shape[player.player_id]
                if self.restart_side is not None and side != self.restart_side:
                    right = attacks_right(side, self.period)
                    local = to_attacking_frame(shape[player.player_id], attacking_right=right)
                    self._targets[player.player_id] = from_attacking_frame(
                        Spot(min(local.x, 43.0), local.y), attacking_right=right
                    )
        self.bodies = {key: body for key, body in self.bodies.items() if key in self._targets}
        if self.dead_ball:
            return
        if self.receive_target is not None:
            self._targets[self.receive_target[0]] = self.receive_target[1]
        if self.flight is not None:
            if self.flight.receiver_id in self._targets:
                self._targets[self.flight.receiver_id] = self.flight.target
        elif self.owner_id in self.bodies:
            self._targets[self.owner_id] = (
                self.carry_target
                if self.controlled and self.carry_target is not None
                else self.bodies[self.owner_id].spot
                if self.controlled
                else clamp_to_pitch(
                    Spot(
                        self.ball.x - math.sin(self.bodies[self.owner_id].heading) * CONTROL_OFFSET,
                        self.ball.y - math.cos(self.bodies[self.owner_id].heading) * CONTROL_OFFSET,
                    )
                )
            )
        if self.restart_side is not None:
            return
        self._defensive_targets()

    def _defensive_targets(self) -> None:
        defending = self.teams[opponent(self.side)]
        near = sorted(
            defending.outfield(),
            key=lambda player: self.bodies[player.player_id].spot.distance_to(self.ball),
        )
        for index, player in enumerate(near[:2]):
            body = self.bodies[player.player_id]
            if body.spot.distance_to(self.ball) > (16 if index == 0 else 24):
                continue
            right = attacks_right(opponent(self.side), self.period)
            local = to_attacking_frame(self.ball, attacking_right=right)
            target = Spot(local.x - (0.6 if index == 0 else 5.0), local.y + (3 if index else 0))
            self._targets[player.player_id] = clamp_to_pitch(
                from_attacking_frame(target, attacking_right=right)
            )
        if self.flight is not None and self.flight.action == "shot":
            keeper = defending.goalkeeper()
            goal_x = 103.8 if attacks_right(self.side, self.period) else 1.2
            self._targets[keeper.player_id] = Spot(
                goal_x, min(37.5, max(30.5, self.flight.target.y))
            )

    def _move_players(self, dt: float) -> None:
        if self.ms >= self._next_targets:
            self._refresh_targets()
            self._next_targets = self.ms + 200
        for team in self.teams.values():
            for player in team.on_pitch():
                body = self.bodies.get(player.player_id)
                if body is None:
                    continue
                target = self._targets.get(player.player_id, body.spot)
                dx, dy = target.x - body.spot.x, target.y - body.spot.y
                gap = math.hypot(dx, dy)
                maximum = 6.0 + player.player.traits.pace * 0.027
                if player.is_goalkeeper:
                    maximum = 5.0
                if self.dead_ball:
                    maximum = 2.8
                speed = min(maximum, gap * 2.2)
                desired = Spot(dx / gap * speed, dy / gap * speed) if gap > 0.01 else Spot(0.0, 0.0)
                desired = self._avoid_bodies(player.player_id, desired)
                acceleration = Spot(desired.x - body.velocity.x, desired.y - body.velocity.y)
                magnitude = math.hypot(*acceleration)
                scale = min(1.0, 3.2 * dt / max(0.001, magnitude))
                body.velocity = Spot(
                    body.velocity.x + acceleration.x * scale,
                    body.velocity.y + acceleration.y * scale,
                )
                desired_heading = body.heading
                if player.player_id == self.owner_id and self.face_target is not None:
                    desired_heading = math.atan2(
                        self.face_target.x - body.spot.x, self.face_target.y - body.spot.y
                    )
                elif math.hypot(*body.velocity) > 0.15:
                    desired_heading = math.atan2(body.velocity.x, body.velocity.y)
                turn = _angle(desired_heading - body.heading)
                body.heading = _angle(body.heading + max(-4.5 * dt, min(4.5 * dt, turn)))
        self._advance_bodies(dt)
        self._separate(dt)
        self._body_steps.append((1.0, {key: body.spot for key, body in self.bodies.items()}))

    def _avoid_bodies(self, player_id: str, desired: Spot) -> Spot:
        speed = math.hypot(*desired)
        if speed < 0.1:
            return desired
        body = self.bodies[player_id]
        ux, uy = desired.x / speed, desired.y / speed
        adjustment = 0.0
        for other_id, other in self.bodies.items():
            if other_id == player_id:
                continue
            dx, dy = other.spot.x - body.spot.x, other.spot.y - body.spot.y
            ahead, lateral = dx * ux + dy * uy, dx * uy - dy * ux
            if 0 < ahead < 2.8 and abs(lateral) < BODY_GAP + 0.3:
                adjustment = max(adjustment, (1 - ahead / 2.8) * min(speed, 2.5))
        # Both approaching players prefer their own right, producing opposite
        # world-space detours. Collision response remains authoritative.
        return Spot(desired.x + uy * adjustment, desired.y - ux * adjustment)

    def _advance_bodies(self, dt: float) -> None:
        remaining, elapsed = dt, 0.0
        self._body_steps = [(0.0, {key: body.spot for key, body in self.bodies.items()})]
        for _ in range(24):
            ends = {
                key: clamp_to_pitch(
                    Spot(
                        body.spot.x + body.velocity.x * remaining,
                        body.spot.y + body.velocity.y * remaining,
                    )
                )
                for key, body in self.bodies.items()
            }
            hit: tuple[float, str, str | None] | None = None
            items = list(self.bodies.items())
            for index, (key, body) in enumerate(items):
                if (
                    self.flight is None
                    and self.height < BODY_HEIGHT
                    and not (key == self.owner_id and self.controlled)
                ):
                    fraction = _approaching_sweep(
                        body.spot, ends[key], self.ball, self.ball, BALL_BODY_GAP
                    )
                    if fraction is not None and (hit is None or fraction < hit[0]):
                        hit = fraction, key, None
                for other_key, other in items[:index]:
                    # Cheap broad phase before solving relative swept discs.
                    reach = BODY_GAP + remaining * (
                        math.hypot(*body.velocity) + math.hypot(*other.velocity)
                    )
                    if (
                        abs(body.spot.x - other.spot.x) > reach
                        or abs(body.spot.y - other.spot.y) > reach
                    ):
                        continue
                    fraction = _approaching_sweep(
                        body.spot, ends[key], other.spot, ends[other_key], BODY_GAP
                    )
                    if fraction is not None and (hit is None or fraction < hit[0]):
                        hit = fraction, key, other_key
            fraction = hit[0] if hit else 1.0
            for key, body in items:
                body.spot = body.spot.toward(ends[key], fraction)
            elapsed += remaining * fraction
            remaining *= 1 - fraction
            self._body_steps.append((elapsed / dt, {key: body.spot for key, body in items}))
            if hit is None:
                return
            body = self.bodies[hit[1]]
            other = self.bodies.get(hit[2] or "")
            centre = other.spot if other else self.ball
            gap = max(1e-9, body.spot.distance_to(centre))
            nx, ny = (body.spot.x - centre.x) / gap, (body.spot.y - centre.y) / gap
            relative = Spot(
                body.velocity.x - (other.velocity.x if other else 0),
                body.velocity.y - (other.velocity.y if other else 0),
            )
            closing = min(0.0, relative.x * nx + relative.y * ny)
            impulse = -closing / (2 if other else 1)
            body.velocity = Spot(body.velocity.x + nx * impulse, body.velocity.y + ny * impulse)
            if other is not None and hit[2] is not None:
                other.velocity = Spot(
                    other.velocity.x - nx * impulse, other.velocity.y - ny * impulse
                )
            if remaining < 1e-6:
                return
        # A crowded contact chain may exhaust the iteration budget. Holding
        # the remaining displacement is safe; advancing unchecked is not.

    def _separate(self, dt: float) -> None:
        del dt
        for _ in range(24):
            if not self._project_bodies():
                break

    def _project_bodies(self) -> bool:
        changed = False
        cells: dict[tuple[int, int], list[str]] = {}
        for player_id, body in self.bodies.items():
            cell = int(body.spot.x // 2), int(body.spot.y // 2)
            for x in range(cell[0] - 1, cell[0] + 2):
                for y in range(cell[1] - 1, cell[1] + 2):
                    for other_id in cells.get((x, y), ()):
                        other = self.bodies[other_id]
                        dx, dy = body.spot.x - other.spot.x, body.spot.y - other.spot.y
                        gap = math.hypot(dx, dy)
                        if gap >= BODY_GAP - 1e-7:
                            continue
                        if gap < 0.001:
                            dx, dy, gap = 1.0, 0.0, 1e-9
                        nx, ny = (1.0, 0.0) if gap < 0.001 else (dx / gap, dy / gap)
                        amount = (BODY_GAP - gap + 1e-6) / 2
                        correction = Spot(nx * amount, ny * amount)
                        body.spot = clamp_to_pitch(
                            Spot(body.spot.x + correction.x, body.spot.y + correction.y)
                        )
                        other.spot = clamp_to_pitch(
                            Spot(other.spot.x - correction.x, other.spot.y - correction.y)
                        )
                        changed = True
            cells.setdefault(cell, []).append(player_id)
        return changed

    def _control_ball(self, dt: float, old_players: dict[str, Spot]) -> None:
        body = self.bodies.get(self.owner_id or "")
        if body is None:
            return
        foot = clamp_to_pitch(
            Spot(
                body.spot.x + math.sin(body.heading) * CONTROL_OFFSET,
                body.spot.y + math.cos(body.heading) * CONTROL_OFFSET,
            )
        )
        gap = self.ball.distance_to(foot)
        if not self.controlled and gap > 1.1:
            return
        # A first touch draws the ball into control over time, not a teleport.
        target = self.ball.toward(foot, min(1.0, 9.0 * dt / max(0.001, gap)))
        hits = self._step_ball_contacts(self.ball, target, 0.0, 0.0, old_players, flight=False)
        fraction = min((hit[0] for hit in hits), default=1.0)
        self.ball = self.ball.toward(target, fraction)
        if fraction < 1.0:
            self._stop_bodies_at(fraction)
        self.height = 0.0
        self.controlled = self.ball.distance_to(foot) < 0.08
        if fraction < 1.0 and self.record:
            self._sample_ball(self.ms - self._frame_start_ms + round(dt * 1000 * fraction))

    def _move_ball(self, dt: float, old_players: dict[str, Spot]) -> None:
        flight = self.flight
        if flight is None:
            return
        before, old_height = self.ball, self.height
        speed = math.hypot(*flight.velocity)
        if self.height <= 0 and flight.vertical_speed <= 0:
            after_speed = max(0.0, speed - ROLL_DECELERATION * dt)
            distance = (speed + after_speed) * dt / 2
            after = Spot(
                before.x + flight.velocity.x / max(0.001, speed) * distance,
                before.y + flight.velocity.y / max(0.001, speed) * distance,
            )
            flight.velocity = Spot(
                flight.velocity.x * after_speed / max(0.001, speed),
                flight.velocity.y * after_speed / max(0.001, speed),
            )
            height = 0.0
        else:
            after = Spot(before.x + flight.velocity.x * dt, before.y + flight.velocity.y * dt)
            height = old_height + flight.vertical_speed * dt - GRAVITY * dt * dt / 2
            flight.vertical_speed -= GRAVITY * dt
            if height < 0:
                height = 0.0
                flight.vertical_speed = max(0.0, -flight.vertical_speed * 0.48)
                if flight.vertical_speed < 0.9:
                    flight.vertical_speed = 0.0
                flight.velocity = Spot(flight.velocity.x * 0.82, flight.velocity.y * 0.82)
        hits = self._step_ball_contacts(before, after, old_height, height, old_players, flight=True)
        boundary = _boundary(before, after)
        if boundary is not None:
            hits.append((boundary[0], None))
        if hits:
            fraction, player_id = min(hits, key=lambda hit: hit[0])
            # End this integration step at the contact configuration. Otherwise
            # a moving defender could already be beyond the stopped ball in
            # the recorded contact frame.
            self._stop_bodies_at(fraction)
            self.ball = clamp_to_pitch(before.toward(after, fraction))
            self.height = max(0.0, old_height + (height - old_height) * fraction)
            flight.travelled += before.distance_to(after) * fraction
            self.contact = self._contact_result(player_id)
            if self.record:
                self._sample_ball(self.ms - self._frame_start_ms + round(dt * 1000 * fraction))
        else:
            self.ball, self.height = clamp_to_pitch(after), height
            flight.travelled += before.distance_to(after)
            if math.hypot(*flight.velocity) < 0.3 or self.ms - flight.started_ms >= 8000:
                self.contact = Contact("loose", self.ball)

    def _contacts(  # noqa: PLR0913 - start/end ball and body sweep inputs
        self,
        before: Spot,
        after: Spot,
        old_height: float,
        height: float,
        old_players: dict[str, Spot],
        *,
        new_players: dict[str, Spot] | None = None,
    ) -> list[tuple[float, str | None]]:
        flight = self.flight
        if flight is None:
            return []
        hits = self._body_ball_contacts(
            before, after, old_height, height, old_players, new_players=new_players
        )
        for side, team in self.teams.items():
            for player in team.on_pitch():
                body = self.bodies.get(player.player_id)
                if body is None:
                    continue
                # Deliberate receiving/catching reach is additional to the hard
                # body collider, which applies to every player on both teams.
                receiving = player.player_id == flight.receiver_id
                catching = player.is_goalkeeper and side != flight.side and flight.action == "shot"
                if not receiving and not catching:
                    continue
                radius = 1.1 if receiving else 1.2
                previous = old_players.get(player.player_id, body.spot)
                a = Spot(before.x - previous.x, before.y - previous.y)
                end_spot = (new_players or {}).get(player.player_id, body.spot)
                b = Spot(after.x - end_spot.x, after.y - end_spot.y)
                fraction = _sweep_volume(
                    a, b, radius, (old_height, height), 1.45 if receiving else 2.5
                )
                if fraction is None:
                    continue
                hits.append((fraction, player.player_id))
        return hits

    def _body_ball_contacts(  # noqa: PLR0913 - start/end ball and body sweep inputs
        self,
        before: Spot,
        after: Spot,
        old_height: float,
        height: float,
        old_players: dict[str, Spot],
        *,
        new_players: dict[str, Spot] | None = None,
    ) -> list[tuple[float, str | None]]:
        hits: list[tuple[float, str | None]] = []
        for key, body in self.bodies.items():
            previous = old_players.get(key, body.spot)
            start = Spot(before.x - previous.x, before.y - previous.y)
            end_spot = (new_players or {}).get(key, body.spot)
            end = Spot(after.x - end_spot.x, after.y - end_spot.y)
            # Allow an initial contact to separate, including the releasing
            # foot. No player is ignored for the rest of a flight.
            if math.hypot(*start) <= BALL_BODY_GAP + 1e-6 and (
                start.x * (end.x - start.x) + start.y * (end.y - start.y) >= -1e-8
            ):
                continue
            fraction = _sweep_volume(start, end, BALL_BODY_GAP, (old_height, height), BODY_HEIGHT)
            if fraction is not None:
                hits.append((fraction, key))
        return hits

    def _step_ball_contacts(  # noqa: PLR0913 - moving-volume sweep inputs
        self,
        before: Spot,
        after: Spot,
        old_height: float,
        height: float,
        old_players: dict[str, Spot],
        *,
        flight: bool,
    ) -> list[tuple[float, str | None]]:
        steps = self._body_steps or [
            (0.0, old_players),
            (1.0, {key: body.spot for key, body in self.bodies.items()}),
        ]
        hits: list[tuple[float, str | None]] = []
        for (start_at, starts), (end_at, ends) in pairwise(steps):
            if end_at <= start_at:
                continue
            collide = self._contacts if flight else self._body_ball_contacts
            contacts = collide(
                before.toward(after, start_at),
                before.toward(after, end_at),
                old_height + (height - old_height) * start_at,
                old_height + (height - old_height) * end_at,
                starts,
                new_players=ends,
            )
            hits.extend(
                (start_at + (end_at - start_at) * fraction, key) for fraction, key in contacts
            )
        return hits

    def _stop_bodies_at(self, fraction: float) -> None:
        for (start_at, starts), (end_at, ends) in pairwise(self._body_steps):
            if end_at < fraction or end_at <= start_at:
                continue
            t = max(0.0, min(1.0, (fraction - start_at) / (end_at - start_at)))
            for key, body in self.bodies.items():
                body.spot = starts.get(key, body.spot).toward(ends.get(key, body.spot), t)
            positions = {key: body.spot for key, body in self.bodies.items()}
            self._body_steps = [(at, points) for at, points in self._body_steps if at < fraction]
            self._body_steps.extend([(fraction, positions), (1.0, positions)])
            return

    def _contact_result(self, player_id: str | None) -> Contact:
        flight = self.flight
        if flight is None:
            raise RuntimeError("contact without flight")
        if player_id is not None:
            player = next(
                player
                for team in self.teams.values()
                for player in team.on_pitch()
                if player.player_id == player_id
            )
            outcome: Literal["complete", "intercepted", "blocked", "saved"] = (
                "complete"
                if flight.action == "pass"
                and any(
                    player.player_id == player_id for player in self.teams[flight.side].on_pitch()
                )
                else "saved"
                if flight.action == "shot"
                and player.is_goalkeeper
                and player in self.teams[opponent(flight.side)].on_pitch()
                else "blocked"
                if flight.action == "shot"
                else "intercepted"
            )
            return Contact(outcome, self.ball, player_id)
        right = attacks_right(flight.side, self.period)
        goal_line = self.ball.x >= 104.99 if right else self.ball.x <= 0.01
        within_posts = abs(self.ball.y - 34.0) < 3.66
        if flight.action == "shot" and goal_line:
            if (abs(abs(self.ball.y - 34.0) - 3.66) < 0.16 and self.height < 2.6) or (
                abs(self.height - 2.44) < 0.16 and abs(self.ball.y - 34.0) < 3.8
            ):
                return Contact("woodwork", self.ball)
            if within_posts and self.height < 2.44:
                return Contact("goal", self.ball)
        return Contact("out", self.ball)

    def _record_initial(self) -> None:
        if not self.record:
            return
        self._sample_ball(0)
        self._sample_players(0)
        self._write_frame()
        self._next_frame = 1000

    def _capture(self) -> None:
        self._sample_ball(self.ms - self._frame_start_ms)
        # Keep all movement knots, including away from the ball: endpoint
        # interpolation can cut straight through a legitimate avoidance turn.
        self._sample_players(self.ms - self._frame_start_ms)
        if self.ms == self._next_frame or self.contact is not None:
            self._write_frame()
        if self.ms == self._next_frame:
            self._next_frame += 1000

    def _sample_ball(self, offset: int, *, previous: bool = False) -> None:
        flight = self.flight
        ball = self._previous_ball if previous else self.ball
        length = max(0.1, flight.origin.distance_to(flight.target)) if flight else 1.0
        while self._samples and self._samples[-1].offset_ms >= offset:
            self._samples.pop()
        action = (
            flight.action
            if flight
            else self.preparing or ("carry" if self.controlled and not self.dead_ball else "hold")
        )
        actor_id = flight.actor_id if flight else self.owner_id if self.controlled else None
        progress = min(1.0, flight.travelled / length) if flight else 0.0
        if self.preparing:
            progress = min(1.0, (self.ms - self._preparation_ms) / 200)
        recent = (self.ms, self.contact) if self.contact is not None else self._last_contact
        if recent is not None and self.ms - recent[0] < 350 and recent[1].player_id:
            kind = recent[1].outcome
            action = "save" if kind == "saved" else "block" if kind == "blocked" else "receive"
            actor_id = recent[1].player_id
            progress = max(0.0, (self.ms - recent[0]) / 350)
        self._samples.append(
            BallSample(
                offset_ms=offset,
                x=round(ball.x, 3),
                y=round(ball.y, 3),
                height_m=round(max(0.0, min(12.0, self.height)), 3),
                action=action,
                actor_id=actor_id,
                progress=progress,
                preparing=self.preparing is not None,
            )
        )

    def _sample_players(self, offset: int, positions: dict[str, Spot] | None = None) -> None:
        for player_id, body in self.bodies.items():
            path = self._paths.setdefault(player_id, [])
            while path and path[-1][0] >= offset:
                path.pop()
            spot = (positions or {}).get(player_id, body.spot)
            sample = (offset, round(spot.x, 3), round(spot.y, 3), round(body.heading, 4))
            # An unchanged hold needs only its first and last knot. Moving
            # paths retain their contact/avoidance geometry without fitting.
            if len(path) >= 2 and path[-2][1:] == path[-1][1:] == sample[1:]:
                path.pop()
            path.append(sample)

    def _write_frame(self) -> None:
        speed = (
            self._previous_ball.distance_to(self.ball)
            * 3.6
            * 1000
            / (self.ms - self._frame_start_ms)
            if self.ms > self._frame_start_ms and not self._placed_since_frame
            else 0.0
        )
        players = [
            PlayerPos(
                player_id=player_id,
                x=round(body.spot.x, 3),
                y=round(body.spot.y, 3),
                speed_kmh=round(math.hypot(*body.velocity) * 3.6, 2),
            )
            for player_id, body in self.bodies.items()
        ]
        self.frames.append(
            TrackingFrame(
                match_id=self.match_id,
                frame_seq=len(self.frames) + 1,
                interval_ms=self.ms - self._frame_start_ms,
                clock=MatchClock(period=self.period, ms=self.ms),
                ball=Point(x=round(self.ball.x, 3), y=round(self.ball.y, 3)),
                ball_speed_kmh=round(speed, 2),
                players=players,
                ball_trajectory=self._samples,
                player_trajectories=self._paths,
            )
        )
        self._previous_ball = self.ball
        self._frame_start_ms = self.ms
        self._placed_since_frame = False
        self._samples, self._paths = [], {}
        self._sample_ball(0)
        self._sample_players(0)


def _angle(value: float) -> float:
    return math.atan2(math.sin(value), math.cos(value))


def _sweep(start: Spot, end: Spot, radius: float) -> float | None:
    dx, dy = end.x - start.x, end.y - start.y
    c = start.x * start.x + start.y * start.y - radius * radius
    if c <= 0:
        return 0.0
    a = dx * dx + dy * dy
    if a < 1e-10:
        return None
    b = 2 * (start.x * dx + start.y * dy)
    discriminant = b * b - 4 * a * c
    if discriminant < 0:
        return None
    fraction = (-b - math.sqrt(discriminant)) / (2 * a)
    return fraction if 0 <= fraction <= 1 else None


def _approaching_sweep(
    start: Spot, end: Spot, other_start: Spot, other_end: Spot, radius: float
) -> float | None:
    relative = Spot(start.x - other_start.x, start.y - other_start.y)
    finish = Spot(end.x - other_end.x, end.y - other_end.y)
    closing = relative.x * (finish.x - relative.x) + relative.y * (finish.y - relative.y)
    if closing >= -1e-9:
        return None
    return _sweep(relative, finish, radius)


def _sweep_volume(
    start: Spot, end: Spot, radius: float, heights: tuple[float, float], top: float
) -> float | None:
    """Intersect horizontal entry/exit with the vertical body interval."""
    old_height, height = heights
    entry = _sweep(start, end, radius)
    if entry is None:
        return None
    dx, dy = end.x - start.x, end.y - start.y
    a = dx * dx + dy * dy
    exit_at = 1.0
    if a > 1e-10:
        b = 2 * (start.x * dx + start.y * dy)
        c = start.x * start.x + start.y * start.y - radius * radius
        exit_at = min(1.0, (-b + math.sqrt(max(0.0, b * b - 4 * a * c))) / (2 * a))
    change = height - old_height
    if abs(change) < 1e-10:
        return entry if old_height <= top else None
    crossing = (top - old_height) / change
    if change < 0:
        entry = max(entry, crossing)
    else:
        exit_at = min(exit_at, crossing)
    return entry if 0 <= entry <= exit_at else None


def _boundary(start: Spot, end: Spot) -> tuple[float, Spot] | None:
    crossings: list[float] = []
    for a, b, upper in ((start.x, end.x, 105.0), (start.y, end.y, 68.0)):
        if b < 0 <= a and b != a:
            crossings.append(-a / (b - a))
        elif b > upper >= a and b != a:
            crossings.append((upper - a) / (b - a))
    if not crossings:
        return None
    fraction = min(crossings)
    return fraction, start.toward(end, fraction)
