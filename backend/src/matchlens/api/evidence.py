from __future__ import annotations

import asyncio
import math
from hashlib import sha256
from typing import TYPE_CHECKING, cast

from matchlens.agents.evidence import moment_evidence
from matchlens.agents.verifier import verify_claims
from matchlens.metrics.engine import MetricsEngine, progress_x
from matchlens.models.clock import MatchClock
from matchlens.models.events import (
    CarryEvent,
    DuelEvent,
    FoulEvent,
    GoalEvent,
    InterceptionEvent,
    PassEvent,
    PossessionChangeEvent,
    ShotEvent,
    TackleEvent,
)
from matchlens.models.evidence import (
    ClaimEvidence,
    EvidenceReplay,
    EvidenceVersion,
    InsightEvidence,
)
from matchlens.models.insights import Claim
from matchlens.models.tracking import TrackingFrame

if TYPE_CHECKING:
    from matchlens.api.matches import MatchSession
    from matchlens.models.events import MatchEvent
    from matchlens.models.metrics import MetricSnapshot

REPLAY_CONTEXT_MS = 20_000
SnapshotKey = tuple[str, str, int, int, int]


def _key(snapshot: MetricSnapshot) -> SnapshotKey:
    return (
        snapshot.metric_id,
        snapshot.window,
        snapshot.as_of_seq,
        snapshot.clock.period,
        snapshot.clock.ms,
    )


def _recompute(
    match_id: str,
    events: tuple[MatchEvent, ...],
    frames: tuple[TrackingFrame, ...],
    requested: set[SnapshotKey],
) -> dict[SnapshotKey, float]:
    """Replay raw inputs through the metrics engine, independently of the store.

    Match clock, event sequence and window all participate in the key: tracking
    can update a metric several times without advancing its event sequence.
    """
    engine = MetricsEngine(match_id)
    result: dict[SnapshotKey, float] = {}
    inputs: list[MatchEvent | TrackingFrame] = [*events, *frames]
    inputs.sort(
        key=lambda item: (
            item.clock.period,
            item.clock.ms,
            1 if isinstance(item, TrackingFrame) else 0,
        )
    )
    for item in inputs:
        try:
            snapshots = (
                engine.consume_frame(item)
                if isinstance(item, TrackingFrame)
                else engine.consume_event(item)
            )
        except ValueError:
            # Missing/out-of-order raw history cannot establish a later value.
            # Return only computations completed before the gap.
            break
        for snapshot in snapshots:
            key = _key(snapshot)
            if key in requested:
                result[key] = snapshot.value
    return result


def _method(metric_id: str) -> str:
    suffix = metric_id.rsplit(".", 1)[-1]
    methods = {
        "goals": "Count goal events for this team.",
        "passes": "Count attempted passes for this team or player.",
        "pass_accuracy_pct": "Completed passes / attempted passes x 100.",
        "xg": (
            "Compute chance quality from shot geometry, body part and situation; "
            "sum for team/player totals."
        ),
        "pass_difficulty": "Compute the pass difficulty index from length, height and pressure.",
        "avg_pass_difficulty": "Sum pass difficulty indices / attempted passes by this player.",
        "shot_speed_kmh": "Read the synthetic shot-speed attribute from the cited event.",
        "ball_speed_kmh": "Read the synthetic ball-speed attribute from the cited pass.",
        "speed_kmh": "Read player speed from the tracking sample.",
        "top_speed_kmh": "Maximum observed player speed in the tracking samples.",
        "distance_m": "Sum distances between successive player tracking positions.",
        "sprints": "Count transitions into the sprint-speed band in player tracking.",
        "possession_pct": "Time in possession / total tracked possession time x 100.",
        "field_tilt_pct": (
            "This team's passes ending in its attacking third / "
            "both teams' attacking-third passes x 100."
        ),
        "ppda": (
            "Opponent passes in the build-up zone / this team's defensive actions there; "
            "zero when none occur."
        ),
        "momentum": (
            "Add attacking-action and xG threat contributions with time decay; "
            "bound to -100 to 100. Positive favours home."
        ),
        "control_index": (
            "Combine sustained passing sequences and turnovers over the rolling window; "
            "bound to -100 to 100."
        ),
    }
    return methods.get(suffix, "Recompute this metric from the raw event and tracking stream.")


def _scope(snapshot: MetricSnapshot) -> str:
    window = {
        "match": "Full match",
        "last_5m": "Rolling 5 minutes",
        "last_10m": "Rolling 10 minutes",
    }[snapshot.window]
    minutes, seconds = divmod(snapshot.clock.ms // 1000, 60)
    return (
        f"{window}, through period {snapshot.clock.period} {minutes:02d}:{seconds:02d}. "
        "The short replay is context for this calculation."
    )


def _source_ids(snapshot: MetricSnapshot, events: tuple[MatchEvent, ...]) -> list[str]:
    first_half = max(
        2_700_000, max((event.clock.ms for event in events if event.clock.period == 1), default=0)
    )
    end_ms = snapshot.clock.ms + (first_half if snapshot.clock.period == 2 else 0)
    window_ms = {"match": end_ms, "last_5m": 300_000, "last_10m": 600_000}[snapshot.window]
    prefix = [
        event
        for event in events
        if event.seq <= snapshot.as_of_seq
        and (event.clock.period, event.clock.ms) <= (snapshot.clock.period, snapshot.clock.ms)
        and event.clock.ms + (first_half if event.clock.period == 2 else 0) >= end_ms - window_ms
    ]
    if snapshot.scope == "event":
        return [event.event_id for event in prefix if event.event_id == snapshot.subject_id]
    suffix = snapshot.metric_id.rsplit(".", 1)[-1]
    ids: list[str] = []
    for event in prefix:
        subject = event.team_id if snapshot.scope == "team" else event.player_id
        relevant = subject == snapshot.subject_id
        include = False
        if suffix == "goals" and isinstance(event, GoalEvent) and relevant:
            ids.extend((event.event_id, event.attrs.shot_event_id))
        elif suffix == "xg":
            include = isinstance(event, ShotEvent) and relevant
        elif suffix in {"passes", "pass_accuracy_pct", "avg_pass_difficulty"}:
            include = isinstance(event, PassEvent) and relevant
        elif suffix == "field_tilt_pct" and isinstance(event, PassEvent):
            include = progress_x(event.end_location.x, event.team_id, event.clock.period) >= 70
        elif suffix == "ppda":
            opponent = "away" if snapshot.subject_id == "home" else "home"
            include = (
                isinstance(event, PassEvent)
                and event.team_id == opponent
                and progress_x(event.location.x, opponent, event.clock.period) <= 63
            ) or (
                isinstance(event, TackleEvent | InterceptionEvent | FoulEvent)
                and event.team_id == snapshot.subject_id
                and progress_x(event.location.x, opponent, event.clock.period) <= 63
            )
        elif suffix == "momentum":
            include = isinstance(
                event,
                PassEvent | CarryEvent | ShotEvent | TackleEvent | InterceptionEvent,
            )
        elif suffix == "control_index":
            include = isinstance(
                event,
                PassEvent
                | DuelEvent
                | FoulEvent
                | InterceptionEvent
                | TackleEvent
                | PossessionChangeEvent,
            )
        if include:
            ids.append(event.event_id)
    available = {event.event_id for event in prefix}
    return [event_id for event_id in dict.fromkeys(ids) if event_id in available]


async def inspect_insight(session: MatchSession, insight_id: str) -> InsightEvidence:
    # Only inspect material actually emitted for broadcast. Generated drafts and
    # scheduler-dropped versions never become published stories through this API.
    versions = {cue.profile_id: cue for cue in session.cues if cue.insight_id == insight_id}
    if not versions or session.workflow is None:
        raise LookupError("Published insight not found")
    anchor = session.workflow.evidence.get(insight_id)
    if anchor is None:
        raise LookupError("Generation-time evidence is unavailable for this insight")
    moment = anchor.moment
    pinned = await moment_evidence(moment, anchor.store)
    snapshots: dict[tuple[str, int], MetricSnapshot | None] = {}
    claims_by_profile: dict[str, list[Claim]] = {}
    for profile_id, cue in versions.items():
        claims_by_profile[profile_id] = [
            Claim.model_validate(item) for item in cast("list[object]", cue.data.get("claims", []))
        ]
        for claim in claims_by_profile[profile_id]:
            snapshots[claim.metric_id, claim.as_of_seq] = await anchor.store.get(
                session.metadata.match_id, claim.metric_id, claim.as_of_seq
            )
    cutoff = moment.clock.period, moment.clock.ms
    events = tuple(
        cast("MatchEvent", event)
        for event in session.events
        if event.seq <= moment.seq_end and (event.clock.period, event.clock.ms) <= cutoff
    )
    frames = tuple(
        frame for frame in session.frames if (frame.clock.period, frame.clock.ms) <= cutoff
    )
    requested = {_key(snapshot) for snapshot in snapshots.values() if snapshot is not None}
    recomputed = await asyncio.to_thread(
        _recompute, session.metadata.match_id, events, frames, requested
    )
    output: list[EvidenceVersion] = []
    for profile_id, cue in versions.items():
        claims = claims_by_profile[profile_id]
        candidate = anchor.insight.model_copy(
            update={"headline": cue.headline, "body": cue.body, "claims": claims}
        )
        errors = await verify_claims(candidate, moment, anchor.store, cue.language)
        checks: list[ClaimEvidence] = []
        for claim in claims:
            snapshot = snapshots[claim.metric_id, claim.as_of_seq]
            value = recomputed.get(_key(snapshot)) if snapshot is not None else None
            checks.append(
                ClaimEvidence(
                    claim=claim,
                    snapshot=snapshot,
                    recomputed_value=value,
                    recomputation=(
                        "unavailable"
                        if value is None or snapshot is None
                        else "matched"
                        if math.isclose(value, snapshot.value, abs_tol=0.0001)
                        else "mismatch"
                    ),
                    method=_method(claim.metric_id),
                    scope_note=_scope(snapshot)
                    if snapshot
                    else "No pinned metric snapshot is available.",
                    source_event_ids=_source_ids(snapshot, events) if snapshot else [],
                )
            )
        output.append(
            EvidenceVersion(
                cue=cue,
                claims=checks,
                numeric_check_passed=not errors
                and all(check.recomputation == "matched" for check in checks),
                errors=errors,
            )
        )
    start_ms = max(0, moment.clock.ms - REPLAY_CONTEXT_MS)
    replay_frames = [
        frame
        for frame in frames
        if frame.clock.period == moment.clock.period and frame.clock.ms >= start_ms
    ]
    replay_events = [
        event
        for event in events
        if event.clock.period == moment.clock.period and event.clock.ms >= start_ms
    ]
    digest = sha256(
        (
            moment.model_dump_json()
            + anchor.insight.model_dump_json()
            + "".join(snapshot.model_dump_json() for snapshot in pinned)
        ).encode()
    ).hexdigest()[:24]
    return InsightEvidence(
        evidence_id=f"evidence-{digest}",
        insight_id=insight_id,
        match_id=session.metadata.match_id,
        moment=moment,
        versions=output,
        replay=EvidenceReplay(
            start=MatchClock(period=moment.clock.period, ms=start_ms),
            end=moment.clock,
            frames=replay_frames,
            events=replay_events,
            note=(
                "Historical context ending at this insight's evidence cutoff. "
                "Later match events are excluded. Aggregate metrics may use a longer window."
            ),
        ),
        traces=[trace for trace in session.traces if trace.moment_id == moment.moment_id],
        interpretation_note=(
            "Numbers are checked against the saved evidence. Tactical explanations are "
            "interpretations; this check does not establish causation."
        ),
        replay_duration_ms=(replay_frames[-1].clock.ms - replay_frames[0].clock.ms)
        if replay_frames
        else 0,
    )
