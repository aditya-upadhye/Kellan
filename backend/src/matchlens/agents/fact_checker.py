from __future__ import annotations

import time
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING

from matchlens.agents.verifier import verify_claims
from matchlens.llm.client import LLMDisabledError
from matchlens.models.insights import Claim, Insight
from matchlens.models.traces import AgentTrace
from matchlens.obs.telemetry import current_trace_id

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from matchlens.agents.explainer import ExplainerAgent
    from matchlens.models.base import TeamSide
    from matchlens.models.insights import CheckError, Moment
    from matchlens.models.metrics import MetricSnapshot
    from matchlens.models.traces import TraceStatus
    from matchlens.store.base import MetricStore


_HEADLINES = {
    "goal": "A goal changes the match",
    "big_chance": "A clear chance opens up",
    "card": "A card changes the contest",
    "momentum_swing": "Momentum shifts",
    "press_shift": "The pressing pattern changes",
    "control_shift": "Control of the match shifts",
    "milestone": "A match milestone arrives",
    "speed_alert": "A burst of speed stands out",
    "player_spotlight": "A player comes into focus",
}

_BODIES = {
    "goal": "The goal changes the score and the shape of the contest.",
    "big_chance": "A strong scoring opportunity shapes this passage of play.",
    "card": "The card changes the conditions for the next phase of play.",
    "momentum_swing": "The balance of play changes in this passage.",
    "press_shift": "A change in pressing marks this passage of play.",
    "control_shift": "The balance of control changes in this passage.",
    "milestone": "The match reaches a notable point in its progression.",
    "speed_alert": "A notable sprint marks this passage of play.",
    "player_spotlight": "A player contribution stands out in this passage.",
}


class FactCheckerAgent:
    def __init__(
        self,
        explainer: ExplainerAgent,
        store: MetricStore,
        record_trace: Callable[[AgentTrace], None] | None = None,
    ) -> None:
        self._explainer = explainer
        self._store = store
        self._record_trace = record_trace

    async def create_insight(
        self,
        moment: Moment,
        evidence: list[MetricSnapshot],
        score: Mapping[TeamSide, int],
        names: Mapping[str, str],
        recent_insights: list[Insight],
    ) -> Insight:
        if set(score) != {"home", "away"} or any(value < 0 for value in score.values()):
            raise ValueError("score must contain non-negative home and away totals")
        if any(snapshot.metric_id not in moment.evidence_metric_ids for snapshot in evidence):
            raise ValueError("evidence contains a metric outside the moment")
        errors: list[CheckError] = []
        for attempt in range(1, 4):
            started = time.perf_counter()
            try:
                draft = await self._explainer.explain(
                    moment,
                    evidence,
                    score,
                    names,
                    recent_insights,
                    errors=errors,
                    attempt=attempt,
                )
            except LLMDisabledError:
                self._record(moment, "template", "fallback", "LLM mode is off", started)
                return await self._fallback(moment, attempt)
            except Exception as error:
                self._record(moment, "draft", "error", type(error).__name__, started)
                self._record(moment, "template", "fallback", "model draft failed")
                return await self._fallback(moment, attempt)

            errors = await verify_claims(draft, moment, self._store)
            if not errors:
                self._record(moment, "verify", "approved", f"attempt={attempt}", started)
                return draft.model_copy(update={"status": "verified"})

            codes = ",".join(error.code for error in errors)
            self._record(moment, "verify", "rejected", f"attempt={attempt}; {codes}", started)
            if attempt < 3:
                self._record(moment, "revise", "retry", f"attempt={attempt + 1}; {codes}")

        self._record(moment, "template", "fallback", "verification failed after retries")
        return await self._fallback(moment, 3)

    async def _fallback(self, moment: Moment, attempts: int) -> Insight:
        insight_id = f"ins-{sha256(moment.moment_id.encode()).hexdigest()[:32]}"
        headline = _HEADLINES[moment.type]
        body = _BODIES[moment.type]
        base = Insight(
            insight_id=insight_id,
            moment_id=moment.moment_id,
            headline=headline,
            body=body,
            claims=[],
            tags=[moment.type],
            status="fallback",
            attempts=attempts,
            errors=[],
        )
        for metric_id in moment.evidence_metric_ids:
            snapshot = await self._store.get(moment.match_id, metric_id, moment.seq_end)
            if snapshot is None:
                continue
            value = str(snapshot.value)
            suffix = f" {snapshot.unit}" if snapshot.unit else ""
            span = f"{value}{suffix}"
            candidate = base.model_copy(
                update={
                    "body": f"{body} {snapshot.label} stands at {span}.",
                    "claims": [
                        Claim(
                            claim_id=f"{insight_id}-c1",
                            text_span=span,
                            metric_id=metric_id,
                            value=snapshot.value,
                            as_of_seq=snapshot.as_of_seq,
                        )
                    ],
                }
            )
            if not await verify_claims(candidate, moment, self._store):
                return candidate
        return base

    def _record(
        self,
        moment: Moment,
        action: str,
        status: TraceStatus,
        detail: str,
        started: float | None = None,
    ) -> None:
        if self._record_trace is None:
            return
        self._record_trace(
            AgentTrace(
                trace_id=current_trace_id(),
                match_id=moment.match_id,
                moment_id=moment.moment_id,
                agent="fact_checker",
                action=action,
                status=status,
                latency_ms=round((time.perf_counter() - started) * 1000) if started else 0,
                tokens_in=0,
                tokens_out=0,
                detail=detail[:200],
                ts=datetime.now(UTC),
            )
        )
