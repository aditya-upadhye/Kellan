from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from matchlens.models.base import Contract, Identifier
from matchlens.models.clock import MatchClock
from matchlens.models.metrics import MetricId

MomentType = Literal[
    "goal",
    "big_chance",
    "card",
    "momentum_swing",
    "press_shift",
    "control_shift",
    "milestone",
    "speed_alert",
    "player_spotlight",
]
MomentSource = Literal["rule", "agent", "fallback"]
CheckErrorCode = Literal[
    "unknown_metric",
    "value_mismatch",
    "uncited_number",
    "span_not_found",
    "unsupported_claim",
    "too_long",
]
InsightStatus = Literal["draft", "verified", "rejected", "fallback"]
Score = Annotated[float, Field(ge=0.0, le=1.0)]


class Moment(Contract):
    moment_id: Identifier
    match_id: Identifier
    type: MomentType
    seq_start: int = Field(ge=1)
    seq_end: int = Field(ge=1)
    clock: MatchClock
    rule_score: Score
    significance: Score
    evidence_metric_ids: list[MetricId]
    subject_ids: list[str]
    source: MomentSource

    @model_validator(mode="after")
    def sequence_range_is_ordered(self) -> Self:
        if self.seq_end < self.seq_start:
            raise ValueError("seq_end must not precede seq_start")
        return self


class Claim(Contract):
    claim_id: Identifier
    text_span: str = Field(min_length=1)
    metric_id: MetricId
    value: float
    as_of_seq: int = Field(ge=0)


class CheckError(Contract):
    code: CheckErrorCode
    detail: str


class Insight(Contract):
    insight_id: Identifier
    moment_id: Identifier
    headline: str
    body: str
    claims: list[Claim]
    tags: list[str]
    status: InsightStatus
    attempts: int = Field(ge=0)
    errors: list[CheckError]
