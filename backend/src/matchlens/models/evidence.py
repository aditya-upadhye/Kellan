from typing import Literal

from pydantic import Field

from matchlens.models.base import Contract, Identifier
from matchlens.models.clock import MatchClock
from matchlens.models.cues import OverlayCue
from matchlens.models.events import MatchEvent
from matchlens.models.insights import CheckError, Claim, Moment
from matchlens.models.metrics import MetricSnapshot
from matchlens.models.traces import AgentTrace
from matchlens.models.tracking import TrackingFrame


class ClaimEvidence(Contract):
    claim: Claim
    snapshot: MetricSnapshot | None
    recomputed_value: float | None
    recomputation: Literal["matched", "mismatch", "unavailable"]
    method: str
    scope_note: str
    source_event_ids: list[str]


class EvidenceVersion(Contract):
    cue: OverlayCue
    claims: list[ClaimEvidence]
    numeric_check_passed: bool
    errors: list[CheckError]


class EvidenceReplay(Contract):
    start: MatchClock
    end: MatchClock
    frames: list[TrackingFrame]
    events: list[MatchEvent]
    note: str


class InsightEvidence(Contract):
    evidence_id: Identifier
    insight_id: Identifier
    match_id: Identifier
    moment: Moment
    versions: list[EvidenceVersion]
    replay: EvidenceReplay
    traces: list[AgentTrace]
    interpretation_note: str
    replay_duration_ms: int = Field(ge=0)
