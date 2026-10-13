from __future__ import annotations

import time
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING

from matchlens.agents.verifier import verify_claims, verify_draft
from matchlens.config import get_settings
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
        *,
        fault_inject_rate: float | None = None,
        record_draft: Callable[[Insight, list[CheckError]], None] | None = None,
    ) -> None:
        rate = get_settings().fault_inject_rate if fault_inject_rate is None else fault_inject_rate
        if not 0.0 <= rate <= 1.0:
            raise ValueError("fault_inject_rate must be between 0 and 1")
        self._explainer = explainer
        self._store = store
        self._record_trace = record_trace
        self._fault_inject_rate = rate
        self._record_draft = record_draft

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
        previous_draft: Insight | None = None
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
                    previous_draft=previous_draft,
                )
            except LLMDisabledError:
                self._record(moment, "template", "fallback", "LLM mode is off", started)
                return await self._fallback(moment, attempt)
            except Exception as error:
                self._record(moment, "draft", "error", type(error).__name__, started)
                self._record(moment, "template", "fallback", "model draft failed")
                return await self._fallback(moment, attempt)

            if attempt == 1:
                draft = self._inject_fault(draft, moment)
            errors = await verify_draft(draft, moment, evidence, self._store)
            if self._record_draft is not None:
                self._record_draft(draft, errors)
            if not errors:
                self._record(moment, "verify", "approved", f"attempt={attempt}", started)
                return draft.model_copy(update={"status": "verified"})

            codes = ",".join(error.code for error in errors)
            self._record_rejection(moment, draft, f"attempt={attempt}; {codes}", started)
            previous_draft = draft
            if attempt < 3:
                self._record(moment, "revise", "retry", f"attempt={attempt + 1}; {codes}")

        self._record(moment, "template", "fallback", "verification failed after retries")
        return await self._fallback(moment, 3)

    def _inject_fault(self, draft: Insight, moment: Moment) -> Insight:
        if not draft.claims or self._fault_inject_rate == 0.0:
            return draft
        digest = sha256(f"{moment.match_id}:{moment.moment_id}".encode()).digest()
        fraction = int.from_bytes(digest[:8], "big") / 2**64
        if fraction >= self._fault_inject_rate:
            return draft
        index = int.from_bytes(digest[8:16], "big") % len(draft.claims)
        claims = list(draft.claims)
        claim = claims[index]
        claims[index] = claim.model_copy(update={"value": claim.value + 1.0})
        self._record(moment, "inject", "ok", f"claim={claim.claim_id}")
        return draft.model_copy(update={"claims": claims})

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

    def _record_rejection(
        self, moment: Moment, draft: Insight, detail: str, started: float
    ) -> None:
        if self._record_trace is None:
            return
        self._record_trace(
            AgentTrace(
                trace_id=current_trace_id(),
                match_id=moment.match_id,
                moment_id=moment.moment_id,
                agent="fact_checker",
                action="verify",
                status="rejected",
                latency_ms=round((time.perf_counter() - started) * 1000),
                tokens_in=0,
                tokens_out=0,
                detail=detail[:200],
                draft_text=f"{draft.headline}\n{draft.body}"[:600],
                ts=datetime.now(UTC),
            )
        )
