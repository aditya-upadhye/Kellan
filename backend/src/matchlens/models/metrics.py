from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from matchlens.models.base import Contract
from matchlens.models.clock import MatchClock

MetricScope = Literal["match", "team", "player", "event"]
MetricWindow = Literal["match", "last_5m", "last_10m"]
MetricUnit = Literal["", "%", "km/h", "m", "xG", "index"]
MetricId = Annotated[
    str, StringConstraints(pattern=r"^(match|team|player|event)(\.[A-Za-z0-9_-]+)+$")
]


class MetricSnapshot(Contract):
    metric_id: MetricId
    scope: MetricScope
    subject_id: str | None
    label: str = Field(min_length=1, max_length=60)
    value: float
    unit: MetricUnit
    window: MetricWindow
    as_of_seq: int = Field(ge=0)
    clock: MatchClock

    @model_validator(mode="after")
    def metric_id_encodes_scope_and_subject(self) -> Self:
        scope, *rest = self.metric_id.split(".")
        if scope != self.scope:
            raise ValueError(f"metric_id {self.metric_id} does not match scope {self.scope}")
        expected_subject = None if self.scope == "match" else rest[0]
        if self.subject_id != expected_subject:
            raise ValueError(f"metric_id {self.metric_id} expects subject_id {expected_subject}")
        return self
