from __future__ import annotations

import json
from hashlib import sha256
from importlib.resources import files
from typing import TYPE_CHECKING

from pydantic import Field

from matchlens.models.base import Contract
from matchlens.models.insights import Claim, Insight
from matchlens.models.metrics import MetricId  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Mapping

    from matchlens.llm.client import LLMClient
    from matchlens.models.base import TeamSide
    from matchlens.models.insights import CheckError, Moment
    from matchlens.models.metrics import MetricSnapshot


class DraftClaim(Contract):
    text_span: str = Field(min_length=1)
    metric_id: MetricId
    value: float
    as_of_seq: int = Field(ge=0)


class ExplainerResponse(Contract):
    headline: str = Field(min_length=1, max_length=60)
    body: str = Field(min_length=1, max_length=280)
    claims: list[DraftClaim]
    tags: list[str]


class ExplainerAgent:
    def __init__(self, client: LLMClient, strong_model: str) -> None:
        self._client = client
        self._strong_model = strong_model

    async def explain(  # noqa: PLR0913
        self,
        moment: Moment,
        evidence: list[MetricSnapshot],
        score: Mapping[TeamSide, int],
        names: Mapping[str, str],
        recent_insights: list[Insight],
        *,
        errors: list[CheckError] | None = None,
        attempt: int = 1,
    ) -> Insight:
        if attempt < 1:
            raise ValueError("attempt must be positive")
        if set(score) != {"home", "away"} or any(value < 0 for value in score.values()):
            raise ValueError("score must contain non-negative home and away totals")
        if any(snapshot.metric_id not in moment.evidence_metric_ids for snapshot in evidence):
            raise ValueError("evidence contains a metric outside the moment")

        user = json.dumps(
            {
                "moment_type": moment.type,
                "moment": moment.model_dump(mode="json"),
                "evidence": [snapshot.model_dump(mode="json") for snapshot in evidence],
                "score": dict(score),
                "minute": (moment.clock.period - 1) * 45 + moment.clock.ms // 60_000,
                "names": dict(names),
                "recent_insights": [
                    {"headline": insight.headline, "body": insight.body}
                    for insight in recent_insights[-3:]
                ],
                "check_errors": [error.model_dump(mode="json") for error in errors or []],
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        response = ExplainerResponse.model_validate(
            await self._client.complete_json(
                "explainer",
                files("matchlens.agents")
                .joinpath("prompts/explainer.md")
                .read_text(encoding="utf-8"),
                user,
                ExplainerResponse.model_json_schema(),
                self._strong_model,
                match_id=moment.match_id,
                moment_id=moment.moment_id,
            )
        )
        insight_id = f"ins-{sha256(moment.moment_id.encode()).hexdigest()[:32]}"
        claims = [
            Claim(
                claim_id=f"{insight_id}-c{index}",
                text_span=claim.text_span,
                metric_id=claim.metric_id,
                value=claim.value,
                as_of_seq=claim.as_of_seq,
            )
            for index, claim in enumerate(response.claims, start=1)
        ]
        return Insight(
            insight_id=insight_id,
            moment_id=moment.moment_id,
            headline=response.headline,
            body=response.body,
            claims=claims,
            tags=response.tags,
            status="draft",
            attempts=attempt,
            errors=[],
        )
