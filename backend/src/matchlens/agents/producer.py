from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from matchlens.models.clock import MatchClock
    from matchlens.models.cues import OverlayCue

NON_CRITICAL_GAP_MS = 20_000
CRITICAL_MOMENTS = frozenset({"goal", "card"})


def priority_for(significance: float, favorite_involved: bool = False) -> int:
    if not 0.0 <= significance <= 1.0:
        raise ValueError("significance must be between 0 and 1")
    return min(100, round(significance * 100) + (20 if favorite_involved else 0))


@dataclass(frozen=True, slots=True)
class ScheduleResult:
    delivered: tuple[OverlayCue, ...] = ()
    expired: tuple[OverlayCue, ...] = ()
    preempted: tuple[OverlayCue, ...] = ()


@dataclass(slots=True)
class _PendingCue:
    cue: OverlayCue
    critical: bool


@dataclass(slots=True)
class _ActiveCue:
    cue: OverlayCue
    ends_at_ms: int


@dataclass(slots=True)
class ProducerScheduler:
    _active: dict[tuple[str, str], _ActiveCue] = field(
        default_factory=dict[tuple[str, str], _ActiveCue]
    )
    _pending: list[_PendingCue] = field(default_factory=list[_PendingCue])
    _last_non_critical: dict[str, int] = field(default_factory=dict[str, int])
    _now_match_ms: int | None = None
    _now_wall_ms: int | None = None

    def offer(
        self, cue: OverlayCue, moment_type: str, now: MatchClock, wall_ms: int
    ) -> ScheduleResult:
        expired, _ = self._advance_time(now, wall_ms)
        if self._elapsed(cue.expires_at) <= self._elapsed(now):
            return ScheduleResult(expired=(*expired, cue))
        if self._elapsed(cue.expires_at) <= self._elapsed(cue.clock):
            raise ValueError("cue expiry must follow its trigger clock")

        critical = moment_type in CRITICAL_MOMENTS
        preempted: list[OverlayCue] = []
        if critical:
            for key, active in list(self._active.items()):
                if key[0] == cue.profile_id and cue.priority > active.cue.priority:
                    preempted.append(self._active.pop(key).cue)
            retained: list[_PendingCue] = []
            for pending in self._pending:
                if pending.cue.profile_id == cue.profile_id and cue.priority > pending.cue.priority:
                    preempted.append(pending.cue)
                else:
                    retained.append(pending)
            self._pending = retained

        self._pending.append(_PendingCue(cue=cue, critical=critical))
        delivered, newly_expired = self._dispatch(self._elapsed(now), wall_ms)
        return ScheduleResult(
            delivered=tuple(delivered),
            expired=(*expired, *newly_expired),
            preempted=tuple(preempted),
        )

    def advance(self, now: MatchClock, wall_ms: int) -> ScheduleResult:
        expired, elapsed = self._advance_time(now, wall_ms)
        delivered, newly_expired = self._dispatch(elapsed, wall_ms)
        return ScheduleResult(delivered=tuple(delivered), expired=(*expired, *newly_expired))

    def _advance_time(self, now: MatchClock, wall_ms: int) -> tuple[list[OverlayCue], int]:
        elapsed = self._elapsed(now)
        if self._now_match_ms is not None and elapsed < self._now_match_ms:
            raise ValueError("producer clock cannot move backwards")
        if self._now_wall_ms is not None and wall_ms < self._now_wall_ms:
            raise ValueError("producer wall clock cannot move backwards")
        self._now_match_ms = elapsed
        self._now_wall_ms = wall_ms
        expired: list[OverlayCue] = []
        for key, active in list(self._active.items()):
            if active.ends_at_ms <= wall_ms or self._is_expired(active.cue, elapsed):
                self._active.pop(key)
                if self._is_expired(active.cue, elapsed):
                    expired.append(active.cue)
        retained: list[_PendingCue] = []
        for pending in self._pending:
            if self._is_expired(pending.cue, elapsed):
                expired.append(pending.cue)
            else:
                retained.append(pending)
        self._pending = retained
        return expired, elapsed

    def _dispatch(self, now_ms: int, wall_ms: int) -> tuple[list[OverlayCue], list[OverlayCue]]:
        delivered: list[OverlayCue] = []
        expired: list[OverlayCue] = []
        self._pending.sort(key=lambda item: (item.cue.trigger_seq, item.cue.profile_id))
        retained: list[_PendingCue] = []
        blocked_profiles: set[str] = set()
        for pending in self._pending:
            cue = pending.cue
            cue_time = self._elapsed(cue.clock)
            expiry = self._elapsed(cue.expires_at)
            if now_ms >= expiry:
                expired.append(cue)
                continue
            if cue.profile_id in blocked_profiles:
                retained.append(pending)
                continue
            key = (cue.profile_id, cue.slot)
            if key in self._active:
                retained.append(pending)
                blocked_profiles.add(cue.profile_id)
                continue
            eligible_at = cue_time
            if not pending.critical:
                last_delivered = self._last_non_critical.get(cue.profile_id)
                if last_delivered is not None:
                    eligible_at = max(eligible_at, last_delivered + NON_CRITICAL_GAP_MS)
            if now_ms < eligible_at:
                retained.append(pending)
                blocked_profiles.add(cue.profile_id)
                continue
            delivered.append(cue)
            self._active[key] = _ActiveCue(cue=cue, ends_at_ms=wall_ms + cue.duration_ms)
            if not pending.critical:
                self._last_non_critical[cue.profile_id] = now_ms
        self._pending = retained
        return delivered, expired

    @staticmethod
    def _is_expired(cue: OverlayCue, now_ms: int) -> bool:
        return now_ms >= ProducerScheduler._elapsed(cue.expires_at)

    @staticmethod
    def _elapsed(clock: MatchClock) -> int:
        return (clock.period - 1) * 45 * 60_000 + clock.ms
