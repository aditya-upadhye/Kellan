from typing import Literal

from pydantic import AwareDatetime, Field

from matchlens.models.base import Contract, Identifier

AgentName = Literal["detector", "explainer", "fact_checker", "personalizer", "producer"]
TraceStatus = Literal["ok", "approved", "rejected", "retry", "fallback", "error"]


class AgentTrace(Contract):
    trace_id: Identifier
    match_id: Identifier
    moment_id: Identifier | None
    agent: AgentName
    action: str = Field(min_length=1, max_length=60)
    status: TraceStatus
    latency_ms: int = Field(ge=0)
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    detail: str = Field(max_length=200)
    draft_text: str | None = Field(default=None, max_length=600)
    ts: AwareDatetime
