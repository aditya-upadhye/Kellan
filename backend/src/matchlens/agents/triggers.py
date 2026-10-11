from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from matchlens.models.events import CardEvent, GoalEvent, ShotEvent
from matchlens.models.insights import Moment, MomentType
from matchlens.models.tracking import TrackingFrame

if TYPE_CHECKING:
    from matchlens.models.base import TeamSide
    from matchlens.models.clock import MatchClock
    from matchlens.models.events import MatchEvent
    from matchlens.models.metrics import MetricSnapshot

FIVE_MIN_MS = 5 * 60_000
TEN_MIN_MS = 10 * 60_000
SPOTLIGHT_INTERVAL_MS = 15 * 60_000
MERGE_WINDOW_MS = 30_000
CRITICAL_MOMENTS = {"goal", "card"}
MOMENT_SCORES: dict[MomentType, float] = {
    "goal": 1.0,
    "card": 0.9,
    "big_chance": 0.6,
    "momentum_swing": 0.7,
    "press_shift": 0.5,
    "control_shift": 0.4,
    "speed_alert": 0.4,
    "milestone": 0.3,
    "player_spotlight": 0.3,
}
SPOTLIGHT_METRICS = ("xg", "passes", "avg_pass_difficulty", "top_speed_kmh", "sprints")


@dataclass(frozen=True, slots=True)
class _Reading:
    elapsed_ms: int
    seq: int
    value: float


@dataclass(frozen=True, slots=True)
class _MomentSpec:
    moment_type: MomentType
    seq_start: int
    seq_end: int
    clock: MatchClock
    subject_ids: list[str]
    evidence_metric_ids: list[str]
    rule_score: float | None = None


class RuleTriggerEngine:
    def __init__(self, match_id: str) -> None:
        self.match_id = match_id
        self._momentum: deque[_Reading] = deque()
        self._ppda: dict[TeamSide, _Reading] = {}
        self._control_label: str | None = None
        self._match_top_speed = 0.0
        self._pass_values: dict[str, float] = {}
        self._shot_on_target_seen = False
        self._performance: dict[str, dict[str, float]] = defaultdict(dict)
        self._spotlight_bucket = 0
        self._last_seq = 0

    def consume(
        self, item: MatchEvent | TrackingFrame, snapshots: list[MetricSnapshot]
    ) -> list[Moment]:
        if item.match_id != self.match_id:
            raise ValueError("match id mismatch")
        candidates: list[Moment] = []
        if isinstance(item, TrackingFrame):
            seq = max((snapshot.as_of_seq for snapshot in snapshots), default=self._last_seq)
            candidates.extend(self._consume_snapshots(snapshots, seq))
            candidates.extend(self._spotlight(item.clock, seq))
            return candidates

        self._last_seq = item.seq
        candidates.extend(self._consume_snapshots(snapshots, item.seq))
        candidates.extend(self._event_moments(item, snapshots))
        candidates.extend(self._spotlight(item.clock, item.seq))
        return candidates

    def _consume_snapshots(self, snapshots: list[MetricSnapshot], seq: int) -> list[Moment]:
        candidates: list[Moment] = []
        for snapshot in snapshots:
            self._update_performance(snapshot)
            elapsed = _elapsed_ms(snapshot.clock)
            metric_id = snapshot.metric_id
            if metric_id == "match.momentum":
                candidates.extend(self._momentum_swing(snapshot, seq, elapsed))
            elif metric_id.startswith("team.") and metric_id.endswith(".ppda"):
                candidates.extend(self._press_shift(snapshot, seq, elapsed))
            elif metric_id == "match.control_index":
                candidates.extend(self._control_shift(snapshot, seq))
            elif metric_id.startswith("player.") and metric_id.endswith(".top_speed_kmh"):
                candidates.extend(self._speed_alert(snapshot, seq))
            elif metric_id.endswith(".passes"):
                candidates.extend(self._pass_milestones(snapshot, seq))
        return candidates

    def _event_moments(self, event: MatchEvent, snapshots: list[MetricSnapshot]) -> list[Moment]:
        evidence = [snapshot.metric_id for snapshot in snapshots]
        if isinstance(event, GoalEvent):
            return [
                _moment(
                    self.match_id,
                    _MomentSpec(
                        "goal", event.seq, event.seq, event.clock, [event.attrs.scorer_id], evidence
                    ),
                )
            ]
        if isinstance(event, CardEvent):
            return [
                _moment(
                    self.match_id,
                    _MomentSpec(
                        "card",
                        event.seq,
                        event.seq,
                        event.clock,
                        [event.player_id],
                        [],
                        0.9 if event.outcome in ("red", "second_yellow") else 0.4,
                    ),
                )
            ]
        if not isinstance(event, ShotEvent):
            return []

        candidates: list[Moment] = []
        xg_snapshot = next(
            (
                snapshot
                for snapshot in snapshots
                if snapshot.metric_id == f"event.{event.event_id}.xg"
            ),
            None,
        )
        if event.outcome != "goal" and xg_snapshot is not None and xg_snapshot.value >= 0.25:
            candidates.append(
                _moment(
                    self.match_id,
                    _MomentSpec(
                        "big_chance",
                        event.seq,
                        event.seq,
                        event.clock,
                        [event.player_id],
                        [xg_snapshot.metric_id],
                    ),
                )
            )
        if not self._shot_on_target_seen and event.outcome in ("saved", "goal"):
            self._shot_on_target_seen = True
            candidates.append(
                _moment(
                    self.match_id,
                    _MomentSpec(
                        "milestone",
                        event.seq,
                        event.seq,
                        event.clock,
                        [event.player_id],
                        [xg_snapshot.metric_id] if xg_snapshot is not None else [],
                    ),
                )
            )
        return candidates

    def _momentum_swing(self, snapshot: MetricSnapshot, seq: int, elapsed: int) -> list[Moment]:
        while self._momentum and self._momentum[0].elapsed_ms < elapsed - FIVE_MIN_MS:
            self._momentum.popleft()
        prior = next(
            (reading for reading in self._momentum if abs(snapshot.value - reading.value) >= 40),
            None,
        )
        reading = _Reading(elapsed, seq, snapshot.value)
        if prior is None:
            self._momentum.append(reading)
            return []
        self._momentum.clear()
        self._momentum.append(reading)
        return [
            _moment(
                self.match_id,
                _MomentSpec(
                    "momentum_swing", prior.seq, seq, snapshot.clock, [], [snapshot.metric_id]
                ),
            )
        ]

    def _press_shift(self, snapshot: MetricSnapshot, seq: int, elapsed: int) -> list[Moment]:
        side = snapshot.subject_id
        if side not in ("home", "away"):
            return []
        team = side
        previous = self._ppda.get(team)
        current = _Reading(elapsed, seq, snapshot.value)
        if previous is None or elapsed - previous.elapsed_ms < TEN_MIN_MS:
            if previous is None:
                self._ppda[team] = current
            return []
        self._ppda[team] = current
        difference = abs(snapshot.value - previous.value)
        changed = difference > 0 if previous.value == 0 else difference / abs(previous.value) >= 0.4
        if not changed:
            return []
        return [
            _moment(
                self.match_id,
                _MomentSpec(
                    "press_shift", previous.seq, seq, snapshot.clock, [team], [snapshot.metric_id]
                ),
            )
        ]

    def _control_shift(self, snapshot: MetricSnapshot, seq: int) -> list[Moment]:
        label = (
            "control" if snapshot.value > 25 else "chaos" if snapshot.value < -25 else "balanced"
        )
        previous = self._control_label
        self._control_label = label
        if previous is None or previous == label:
            return []
        return [
            _moment(
                self.match_id,
                _MomentSpec(
                    "control_shift",
                    seq,
                    seq,
                    snapshot.clock,
                    [previous, label],
                    [snapshot.metric_id],
                ),
            )
        ]

    def _speed_alert(self, snapshot: MetricSnapshot, seq: int) -> list[Moment]:
        if snapshot.value <= self._match_top_speed:
            return []
        self._match_top_speed = snapshot.value
        if snapshot.value < 34 or snapshot.subject_id is None:
            return []
        return [
            _moment(
                self.match_id,
                _MomentSpec(
                    "speed_alert",
                    seq,
                    seq,
                    snapshot.clock,
                    [snapshot.subject_id],
                    [snapshot.metric_id],
                ),
            )
        ]

    def _pass_milestones(self, snapshot: MetricSnapshot, seq: int) -> list[Moment]:
        subject_id = snapshot.subject_id
        if subject_id is None:
            return []
        previous = self._pass_values.get(snapshot.metric_id, 0)
        self._pass_values[snapshot.metric_id] = snapshot.value
        thresholds = (300, 500) if snapshot.scope == "team" else (50, 75, 100)
        crossed = next(
            (threshold for threshold in thresholds if previous < threshold <= snapshot.value), None
        )
        if crossed is None:
            return []
        return [
            _moment(
                self.match_id,
                _MomentSpec(
                    "milestone", seq, seq, snapshot.clock, [subject_id], [snapshot.metric_id]
                ),
            )
        ]

    def _update_performance(self, snapshot: MetricSnapshot) -> None:
        parts = snapshot.metric_id.split(".")
        subject_id = snapshot.subject_id
        if subject_id is None or len(parts) != 3 or parts[0] != "player" or parts[1] != subject_id:
            return
        metric = parts[2]
        if metric in SPOTLIGHT_METRICS:
            self._performance[subject_id][metric] = snapshot.value

    def _spotlight(self, clock: MatchClock, seq: int) -> list[Moment]:
        elapsed = _elapsed_ms(clock)
        bucket = elapsed // SPOTLIGHT_INTERVAL_MS
        if bucket <= self._spotlight_bucket or seq < 1 or not self._performance:
            return []
        self._spotlight_bucket = bucket
        scores = {
            player_id: stats.get("xg", 0) * 100
            + stats.get("passes", 0) * 0.05
            + stats.get("avg_pass_difficulty", 0) * 10
            + stats.get("top_speed_kmh", 0) * 0.05
            + stats.get("sprints", 0) * 2
            for player_id, stats in self._performance.items()
        }
        player_id = max(scores, key=lambda candidate: (scores[candidate], candidate))
        evidence = [
            f"player.{player_id}.{metric}"
            for metric in SPOTLIGHT_METRICS
            if metric in self._performance[player_id]
        ]
        return [
            _moment(
                self.match_id,
                _MomentSpec("player_spotlight", seq, seq, clock, [player_id], evidence),
            )
        ]


def merge_candidates(candidates: list[Moment], window_ms: int = MERGE_WINDOW_MS) -> list[Moment]:
    ordered = sorted(
        candidates, key=lambda candidate: (_elapsed_ms(candidate.clock), candidate.seq_start)
    )
    merged: list[Moment] = []
    for candidate in ordered:
        match = next(
            (
                index
                for index in range(len(merged) - 1, -1, -1)
                if _can_merge(merged[index], candidate, window_ms)
            ),
            None,
        )
        if match is None:
            merged.append(candidate)
            continue
        current = merged[match]
        merged[match] = current.model_copy(
            update={
                "seq_start": min(current.seq_start, candidate.seq_start),
                "seq_end": max(current.seq_end, candidate.seq_end),
                "clock": candidate.clock,
                "rule_score": max(current.rule_score, candidate.rule_score),
                "significance": max(current.significance, candidate.significance),
                "evidence_metric_ids": sorted(
                    set(current.evidence_metric_ids) | set(candidate.evidence_metric_ids)
                ),
                "subject_ids": sorted(set(current.subject_ids) | set(candidate.subject_ids)),
            }
        )
    return merged


def _can_merge(first: Moment, second: Moment, window_ms: int) -> bool:
    if first.match_id != second.match_id or first.type != second.type:
        return False
    if first.type in CRITICAL_MOMENTS or not set(first.subject_ids).intersection(
        second.subject_ids
    ):
        return False
    return abs(_elapsed_ms(first.clock) - _elapsed_ms(second.clock)) <= window_ms


def _moment(match_id: str, spec: _MomentSpec) -> Moment:
    primary_subject = spec.subject_ids[0] if spec.subject_ids else "match"
    moment_id = f"{match_id}-{spec.seq_end}-{spec.moment_type}-{primary_subject}"[:64]
    score = MOMENT_SCORES[spec.moment_type] if spec.rule_score is None else spec.rule_score
    return Moment(
        moment_id=moment_id,
        match_id=match_id,
        type=spec.moment_type,
        seq_start=spec.seq_start,
        seq_end=spec.seq_end,
        clock=spec.clock,
        rule_score=score,
        significance=score,
        evidence_metric_ids=spec.evidence_metric_ids,
        subject_ids=spec.subject_ids,
        source="rule",
    )


def _elapsed_ms(clock: MatchClock) -> int:
    return (clock.period - 1) * 45 * 60_000 + clock.ms
