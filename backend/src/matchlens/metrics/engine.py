import math
from collections import defaultdict, deque
from collections.abc import Iterable
from typing import cast

from matchlens.metrics.difficulty import pass_difficulty
from matchlens.metrics.xg import expected_goals, shot_geometry
from matchlens.models.base import TeamSide
from matchlens.models.clock import MatchClock
from matchlens.models.events import (
    DuelEvent,
    FoulEvent,
    GoalEvent,
    InterceptionEvent,
    MatchEvent,
    PassEvent,
    ShotEvent,
    TackleEvent,
)
from matchlens.models.metrics import MetricScope, MetricSnapshot, MetricUnit, MetricWindow
from matchlens.models.pitch import PITCH_LENGTH_M
from matchlens.models.tracking import TrackingFrame

HALF_MS = 45 * 60_000
FIVE_MIN_MS = 5 * 60_000
TEN_MIN_MS = 10 * 60_000
MOMENTUM_HALF_LIFE_MS = 3 * 60_000


def progress_x(x: float, team: TeamSide, period: int) -> float:
    return x if (team == "home") == (period == 1) else PITCH_LENGTH_M - x


class MetricsEngine:
    """Incremental, match-clock based metrics for one match."""

    def __init__(self, match_id: str) -> None:
        self.match_id = match_id
        self.seq = 0
        self.clock = MatchClock(period=1, ms=0)
        self._now = 0
        self._period_offset = 0
        self._values: dict[tuple[str, MetricWindow], float] = {}
        self._goals: dict[str, int] = defaultdict(int)
        self._passes: dict[str, int] = defaultdict(int)
        self._complete: dict[str, int] = defaultdict(int)
        self._xg: dict[str, float] = defaultdict(float)
        self._difficulty_total: dict[str, float] = defaultdict(float)
        self._possession: TeamSide | None = None
        self._possession_since = 0
        self._possession_intervals: list[tuple[int, int, TeamSide]] = []
        self._actions: deque[tuple[int, TeamSide, str, bool, bool]] = deque()
        self._control: deque[tuple[int, str, int]] = deque()
        self._pass_streak: list[tuple[int, str, int]] = []
        self._streak_team: TeamSide | None = None
        self._momentum = 0.0
        self._momentum_time = 0
        self._last_positions: dict[str, tuple[float, float]] = {}
        self._distance: dict[str, float] = defaultdict(float)
        self._top_speed: dict[str, float] = defaultdict(float)
        self._sprints: dict[str, int] = defaultdict(int)
        self._was_sprinting: dict[str, bool] = defaultdict(bool)

    def _emit(  # noqa: PLR0913, PLR0917 - snapshot metadata is explicit at each call site
        self,
        output: list[MetricSnapshot],
        metric_id: str,
        label: str,
        value: float,
        unit: MetricUnit,
        window: MetricWindow = "match",
    ) -> None:
        value = round(value, 4)
        key = metric_id, window
        if self._values.get(key) == value:
            return
        self._values[key] = value
        parts = metric_id.split(".")
        output.append(
            MetricSnapshot(
                metric_id=metric_id,
                scope=cast("MetricScope", parts[0]),
                subject_id=parts[1] if parts[0] != "match" else None,
                label=label,
                value=value,
                unit=unit,
                window=window,
                as_of_seq=self.seq,
                clock=self.clock,
            )
        )

    def _advance(self, clock: MatchClock, output: list[MetricSnapshot]) -> int:
        if clock.period != self.clock.period:
            self._period_offset = max(HALF_MS, self._now)
        now = self._period_offset + clock.ms
        if now < self._now:
            raise ValueError("match clocks must be monotonic")
        self._now = now
        self.clock = clock
        if self._possession is not None and now > self._possession_since:
            self._possession_intervals.append((self._possession_since, now, self._possession))
            self._possession_since = now
        self._emit_possession(now, output)
        decay = math.exp(-math.log(2) * (now - self._momentum_time) / MOMENTUM_HALF_LIFE_MS)
        self._momentum *= decay
        self._momentum_time = now
        self._emit(output, "match.momentum", "Momentum", self._momentum, "index")
        return now

    def _emit_possession(self, now: int, output: list[MetricSnapshot]) -> None:
        windows: tuple[tuple[MetricWindow, int], ...] = (
            ("match", 0),
            ("last_5m", max(0, now - FIVE_MIN_MS)),
        )
        for window, cutoff in windows:
            durations: dict[TeamSide, int] = defaultdict(int)
            for start, end, side in self._possession_intervals:
                durations[side] += max(0, end - max(start, cutoff))
            total = durations["home"] + durations["away"]
            if total:
                for side in ("home", "away"):
                    self._emit(
                        output,
                        f"team.{side}.possession_pct",
                        "Possession",
                        100 * durations[side] / total,
                        "%",
                        window,
                    )

    def _set_possession(self, side: TeamSide, now: int) -> None:
        if self._possession != side:
            self._possession = side
            self._possession_since = now

    def consume_event(self, event: MatchEvent) -> list[MetricSnapshot]:
        if event.match_id != self.match_id or event.seq != self.seq + 1:
            raise ValueError("event match or sequence mismatch")
        self.seq = event.seq
        output: list[MetricSnapshot] = []
        now = self._advance(event.clock, output)
        side = event.team_id
        if event.type in ("kickoff", "possession_change") and side is not None:
            self._set_possession(side, now)
        if isinstance(event, GoalEvent):
            self._goals[event.team_id] += 1
            self._emit(
                output, f"team.{event.team_id}.goals", "Goals", self._goals[event.team_id], "count"
            )
        if isinstance(event, PassEvent):
            self._record_pass(event, now, output)
        if isinstance(event, ShotEvent):
            self._record_shot(event, output)
        if isinstance(event, (TackleEvent, InterceptionEvent, FoulEvent, DuelEvent)):
            self._record_defense(event, now)
        if side is not None and event.type in ("pass", "carry", "shot", "tackle", "interception"):
            if self._possession != side:
                self._set_possession(side, now)
            if (
                event.location is not None
                and progress_x(event.location.x, side, event.clock.period) >= 70
            ):
                self._add_threat(
                    side,
                    4 if progress_x(event.location.x, side, event.clock.period) >= 88 else 2,
                    output,
                )
        if event.type in ("possession_change", "duel", "foul", "interception", "tackle"):
            self._break_streak(now, event.type)
        self._emit_windows(now, output)
        return output

    def _record_pass(self, event: PassEvent, now: int, output: list[MetricSnapshot]) -> None:
        side, player = event.team_id, event.player_id
        self._passes[side] += 1
        self._passes[player] += 1
        complete = event.outcome == "complete"
        if complete:
            self._complete[side] += 1
            self._complete[player] += 1
        difficulty = pass_difficulty(event)
        self._difficulty_total[player] += difficulty
        self._emit(
            output,
            f"event.{event.event_id}.pass_difficulty",
            "Pass difficulty",
            difficulty,
            "index",
        )
        self._emit(
            output,
            f"player.{player}.avg_pass_difficulty",
            "Average pass difficulty",
            self._difficulty_total[player] / self._passes[player],
            "index",
        )
        self._emit(
            output,
            f"event.{event.event_id}.ball_speed_kmh",
            "Ball speed",
            event.attrs.ball_speed_kmh,
            "km/h",
        )
        for subject in (side, player):
            scope = "team" if subject == side else "player"
            self._emit(
                output, f"{scope}.{subject}.passes", "Passes", self._passes[subject], "count"
            )
            self._emit(
                output,
                f"{scope}.{subject}.pass_accuracy_pct",
                "Pass accuracy",
                100 * self._complete[subject] / self._passes[subject],
                "%",
            )
        own_zone = progress_x(event.location.x, side, event.clock.period) <= 63
        final_third = progress_x(event.end_location.x, side, event.clock.period) >= 70
        self._actions.append((now, side, "pass", own_zone, final_third))
        if self._streak_team != side or not complete:
            self._break_streak(now, "turnover" if not complete else "sequence_end")
            self._streak_team = side if complete else None
        if complete:
            self._pass_streak.append((now, side, 1))

    def _record_shot(self, event: ShotEvent, output: list[MetricSnapshot]) -> None:
        attacking_right = (event.team_id == "home") == (event.clock.period == 1)
        xg = expected_goals(
            shot_geometry(event.location, attacking_right=attacking_right),
            event.attrs.body_part,
            event.attrs.situation,
        )
        self._emit(output, f"event.{event.event_id}.xg", "Expected goals", xg, "xG")
        self._emit(
            output,
            f"event.{event.event_id}.shot_speed_kmh",
            "Shot speed",
            event.attrs.shot_speed_kmh,
            "km/h",
        )
        for scope, subject in (("team", event.team_id), ("player", event.player_id)):
            self._xg[subject] += xg
            self._emit(output, f"{scope}.{subject}.xg", "Expected goals", self._xg[subject], "xG")
        self._add_threat(event.team_id, xg * 100, output)

    def _record_defense(
        self, event: TackleEvent | InterceptionEvent | FoulEvent | DuelEvent, now: int
    ) -> None:
        if isinstance(event, (TackleEvent, InterceptionEvent, FoulEvent)):
            opponent: TeamSide = "away" if event.team_id == "home" else "home"
            if progress_x(event.location.x, opponent, event.clock.period) <= 63:
                self._actions.append((now, event.team_id, "defense", True, False))

    def _break_streak(self, now: int, kind: str) -> None:
        if self._pass_streak:
            if len(self._pass_streak) >= 5:
                self._control.extend(self._pass_streak)
            self._pass_streak = []
        self._streak_team = None
        if kind in ("turnover", "duel", "foul", "interception", "tackle", "possession_change"):
            self._control.append((now, kind, -1))

    def _add_threat(self, side: TeamSide, threat: float, output: list[MetricSnapshot]) -> None:
        self._momentum = max(
            -100, min(100, self._momentum + threat * (1 if side == "home" else -1))
        )
        self._emit(output, "match.momentum", "Momentum", self._momentum, "index")

    def _emit_windows(self, now: int, output: list[MetricSnapshot]) -> None:
        while self._actions and self._actions[0][0] < now - TEN_MIN_MS:
            self._actions.popleft()
        for side in ("home", "away"):
            opponent = "away" if side == "home" else "home"
            own_zone_passes = sum(
                kind == "pass" and team == opponent and own_zone
                for _, team, kind, own_zone, _ in self._actions
            )
            defenses = sum(
                kind == "defense" and team == side for _, team, kind, _, _ in self._actions
            )
            self._emit(
                output,
                f"team.{side}.ppda",
                "Passes per defensive action",
                own_zone_passes / defenses if defenses else 0,
                "ratio",
                "last_10m",
            )
            final_passes = sum(
                kind == "pass" and team == side and final
                for _, team, kind, _, final in self._actions
            )
            all_final = sum(kind == "pass" and final for _, _, kind, _, final in self._actions)
            self._emit(
                output,
                f"team.{side}.field_tilt_pct",
                "Field tilt",
                100 * final_passes / all_final if all_final else 0,
                "%",
                "last_10m",
            )
        while self._control and self._control[0][0] < now - FIVE_MIN_MS:
            self._control.popleft()
        recent_passes = sum(
            kind == "pass" and time >= now - FIVE_MIN_MS for time, _, kind, _, _ in self._actions
        )
        qualified = sum(value == 1 for _, _, value in self._control)
        if len(self._pass_streak) >= 5:
            qualified += sum(time >= now - FIVE_MIN_MS for time, _, _ in self._pass_streak)
        turnovers = sum(value == -1 for _, _, value in self._control)
        control = 100 * qualified / max(1, recent_passes) - min(100, turnovers * 8)
        self._emit(
            output,
            "match.control_index",
            "Control index",
            max(-100, min(100, control)),
            "index",
            "last_5m",
        )

    def consume_frame(self, frame: TrackingFrame) -> list[MetricSnapshot]:
        if frame.match_id != self.match_id:
            raise ValueError("frame match mismatch")
        output: list[MetricSnapshot] = []
        self._advance(frame.clock, output)
        for player in frame.players:
            previous = self._last_positions.get(player.player_id)
            if previous is not None:
                self._distance[player.player_id] += math.dist(previous, (player.x, player.y))
                self._emit(
                    output,
                    f"player.{player.player_id}.distance_m",
                    "Distance covered",
                    self._distance[player.player_id],
                    "m",
                )
            self._last_positions[player.player_id] = player.x, player.y
            if player.speed_kmh > self._top_speed[player.player_id]:
                self._top_speed[player.player_id] = player.speed_kmh
                self._emit(
                    output,
                    f"player.{player.player_id}.top_speed_kmh",
                    "Top speed",
                    player.speed_kmh,
                    "km/h",
                )
            sprinting = player.speed_kmh >= 25
            if sprinting and not self._was_sprinting[player.player_id]:
                self._sprints[player.player_id] += 1
                self._emit(
                    output,
                    f"player.{player.player_id}.sprints",
                    "Sprints",
                    self._sprints[player.player_id],
                    "count",
                )
            self._was_sprinting[player.player_id] = sprinting
        self._emit_windows(self._now, output)
        return output

    def consume_all(self, inputs: Iterable[MatchEvent | TrackingFrame]) -> list[MetricSnapshot]:
        snapshots: list[MetricSnapshot] = []
        for item in inputs:
            snapshots.extend(
                self.consume_frame(item)
                if isinstance(item, TrackingFrame)
                else self.consume_event(item)
            )
        return snapshots
