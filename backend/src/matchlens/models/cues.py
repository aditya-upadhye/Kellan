from typing import Literal

from pydantic import Field, JsonValue

from matchlens.models.base import Contract, Identifier, Language
from matchlens.models.clock import MatchClock
from matchlens.models.insights import Claim
from matchlens.models.metrics import MetricId

CueTemplate = Literal[
    "stat_bar", "player_tag", "moment_card", "momentum_graph", "speed_badge", "recap_panel"
]
CueSlot = Literal["lower_third", "top_right", "side_panel", "full_screen"]
RecapKind = Literal["half", "full"]
RecapStatus = Literal["verified", "fallback"]


class CheckerResult(Contract):
    passed: bool
    attempts: int = Field(ge=0)
    version: str


class CueProvenance(Contract):
    metric_ids: list[MetricId]
    checker: CheckerResult
    model_ids: list[str]


class OverlayCue(Contract):
    cue_id: Identifier
    match_id: Identifier
    profile_id: Identifier
    insight_id: Identifier
    trigger_seq: int = Field(ge=1)
    clock: MatchClock
    template: CueTemplate
    slot: CueSlot
    priority: int = Field(ge=0, le=100)
    start_delay_ms: int = Field(ge=0)
    duration_ms: int = Field(gt=0)
    expires_at: MatchClock
    headline: str
    body: str
    language: Language
    data: dict[str, JsonValue]
    provenance: CueProvenance


class Recap(Contract):
    recap_id: Identifier
    match_id: Identifier
    profile_id: Identifier
    kind: RecapKind
    title: str
    paragraphs: list[str]
    key_moment_ids: list[Identifier]
    claims: list[Claim]
    status: RecapStatus
