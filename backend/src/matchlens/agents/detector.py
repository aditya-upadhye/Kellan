from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from importlib.resources import files
from typing import TYPE_CHECKING

from opentelemetry import trace
from pydantic import Field

from matchlens.agents.triggers import merge_candidates
from matchlens.models.base import Contract
from matchlens.models.traces import AgentTrace, TraceStatus
from matchlens.obs.telemetry import current_trace_id

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from matchlens.llm.client import LLMClient
    from matchlens.models.insights import Moment

DETECTOR_INTERVAL_MS = 15_000
NONCRITICAL_INTERVAL_MS = 5 * 60_000
CRITICAL_TYPES = {"goal", "card"}


class DetectorDecision(Contract):
    moment_id: str
    keep: bool
    significance: float = Field(ge=0.0, le=1.0)


class DetectorResponse(Contract):
    decisions: list[DetectorDecision]
    merge_groups: list[list[str]]


class DetectorAgent:
    def __init__(
        self,
        client: LLMClient,
        fast_model: str,
        record_trace: Callable[[AgentTrace], None] | None = None,
    ) -> None:
        self._client = client
        self._fast_model = fast_model
        self._record_trace = record_trace
        self._pending: dict[str, Moment] = {}
        self._next_review_ms = DETECTOR_INTERVAL_MS
        self._last_noncritical_ms: int | None = None
        self._deferred: Moment | None = None

    async def evaluate(
        self,
        candidates: list[Moment],
        state_summary: Mapping[str, str | float],
        elapsed_ms: int,
    ) -> list[Moment]:
        if elapsed_ms < 0:
            raise ValueError("elapsed_ms must be non-negative")

        critical = self.critical_moments(candidates)
        for candidate in candidates:
            if candidate.type not in CRITICAL_TYPES:
                self._pending[candidate.moment_id] = candidate

        if elapsed_ms < self._next_review_ms:
            return critical
        reviewed = await self._review(state_summary, elapsed_ms)
        return sorted([*critical, *reviewed], key=lambda item: (item.seq_start, item.moment_id))

    async def flush(
        self,
        elapsed_ms: int,
        candidates: list[Moment] | None = None,
        through_seq: int | None = None,
    ) -> list[Moment]:
        if elapsed_ms < 0:
            raise ValueError("elapsed_ms must be non-negative")
        incoming = candidates or []
        critical = self.critical_moments(incoming)
        for candidate in incoming:
            if candidate.type not in CRITICAL_TYPES:
                self._pending[candidate.moment_id] = candidate
        reviewed = await self._review({}, elapsed_ms, through_seq)
        return sorted([*critical, *reviewed], key=lambda item: (item.seq_start, item.moment_id))

    def critical_moments(self, candidates: list[Moment]) -> list[Moment]:
        critical = [candidate for candidate in candidates if candidate.type in CRITICAL_TYPES]
        tracer = trace.get_tracer("matchlens.detector")
        for candidate in critical:
            with tracer.start_as_current_span("matchlens.detector.critical") as span:
                span.set_attribute("matchlens.match_id", candidate.match_id)
                span.set_attribute("matchlens.moment_id", candidate.moment_id)
                self._emit_trace(candidate, "emit", "approved", "critical moment")
        return critical

    async def _review(
        self,
        state_summary: Mapping[str, str | float],
        elapsed_ms: int,
        through_seq: int | None = None,
    ) -> list[Moment]:
        while self._next_review_ms <= elapsed_ms:
            self._next_review_ms += DETECTOR_INTERVAL_MS
        pending = [
            candidate
            for candidate in self._pending.values()
            if through_seq is None or candidate.seq_end <= through_seq
        ]
        pending_ids = {candidate.moment_id for candidate in pending}
        self._pending = {
            moment_id: candidate
            for moment_id, candidate in self._pending.items()
            if moment_id not in pending_ids
        }
        include_deferred = self._deferred is not None and (
            through_seq is None or self._deferred.seq_end <= through_seq
        )
        if not pending and not include_deferred:
            return []
        match_id = pending[0].match_id if pending else None
        if match_id is None and include_deferred and self._deferred is not None:
            match_id = self._deferred.match_id
        tracer = trace.get_tracer("matchlens.detector")
        with tracer.start_as_current_span("matchlens.detector.review") as span:
            span.set_attribute("matchlens.elapsed_ms", elapsed_ms)
            if match_id is not None:
                span.set_attribute("matchlens.match_id", match_id)
            span.set_attribute("matchlens.candidate_count", len(pending))
            if not pending:
                emitted = self._limit_noncritical([], elapsed_ms, include_deferred=include_deferred)
                self._record_pacing([], emitted)
                span.set_attribute("matchlens.emitted_count", len(emitted))
                return emitted

            if (
                self._last_noncritical_ms is not None
                and elapsed_ms - self._last_noncritical_ms < NONCRITICAL_INTERVAL_MS
            ):
                # No noncritical story can air in this interval. Rank/defer by
                # rule evidence without spending a model call on suppressed copy.
                emitted = self._limit_noncritical(
                    pending, elapsed_ms, include_deferred=include_deferred
                )
                self._record_pacing(pending, emitted)
                span.set_attribute("matchlens.model_skipped", "pacing cap")
                span.set_attribute("matchlens.emitted_count", len(emitted))
                return emitted

            started = time.perf_counter()
            response: DetectorResponse | None = None
            fallback_reason = ""
            try:
                response = await self._request_decisions(pending, state_summary)
                reviewed = self._apply_decisions(pending, response)
            except Exception as error:
                response = None
                fallback_reason = f"{type(error).__name__}: {error}"[:200]
                reviewed = _fallback(pending)
                span.set_attribute("matchlens.fallback_reason", fallback_reason)
            latency_ms = round((time.perf_counter() - started) * 1000)
            self._record_decisions(pending, response, fallback_reason, latency_ms)
            emitted = self._limit_noncritical(
                reviewed, elapsed_ms, include_deferred=include_deferred
            )
            self._record_pacing(reviewed, emitted)
            span.set_attribute("matchlens.emitted_count", len(emitted))
            return emitted

    def _record_decisions(
        self,
        candidates: list[Moment],
        response: DetectorResponse | None,
        fallback_reason: str,
        latency_ms: int,
    ) -> None:
        if response is None:
            for candidate in candidates:
                self._emit_trace(candidate, "decide", "fallback", fallback_reason, latency_ms)
            return
        by_id = {candidate.moment_id: candidate for candidate in candidates}
        for decision in response.decisions:
            self._emit_trace(
                by_id[decision.moment_id],
                "decide",
                "approved" if decision.keep else "rejected",
                f"significance={decision.significance:.3f}",
                latency_ms,
            )

    def _record_pacing(self, reviewed: list[Moment], emitted: list[Moment]) -> None:
        emitted_ids = {moment.moment_id for moment in emitted}
        reviewed_ids = {moment.moment_id for moment in reviewed}
        for moment in reviewed:
            if moment.moment_id in emitted_ids:
                self._emit_trace(moment, "emit", "approved", "selected for output")
            elif self._deferred is not None and moment.moment_id == self._deferred.moment_id:
                self._emit_trace(moment, "pace", "retry", "deferred by pacing cap")
            else:
                self._emit_trace(moment, "pace", "rejected", "pacing cap")
        for moment in emitted:
            if moment.moment_id not in reviewed_ids:
                self._emit_trace(moment, "emit", "approved", "deferred moment released")

    def _emit_trace(
        self,
        moment: Moment,
        action: str,
        status: TraceStatus,
        detail: str,
        latency_ms: int = 0,
    ) -> None:
        if self._record_trace is None:
            return
        self._record_trace(
            AgentTrace(
                trace_id=current_trace_id(),
                match_id=moment.match_id,
                moment_id=moment.moment_id,
                agent="detector",
                action=action,
                status=status,
                latency_ms=latency_ms,
                tokens_in=0,
                tokens_out=0,
                detail=detail,
                ts=datetime.now(UTC),
            )
        )

    async def _request_decisions(
        self, candidates: list[Moment], state_summary: Mapping[str, str | float]
    ) -> DetectorResponse:
        user = json.dumps(
            {
                "moment_type": "batch",
                "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
                "state_summary": state_summary,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        schema = DetectorResponse.model_json_schema()
        candidate_ids = [candidate.moment_id for candidate in candidates]
        # Constrain identifiers and row count before generation, while retaining
        # the deterministic duplicate/completeness checks after generation.
        schema["$defs"]["DetectorDecision"]["properties"]["moment_id"]["enum"] = candidate_ids
        schema["properties"]["decisions"].update(
            {"minItems": len(candidates), "maxItems": len(candidates)}
        )
        schema["properties"]["merge_groups"]["items"]["items"]["enum"] = candidate_ids
        payload = await self._client.complete_json(
            "detector",
            _system_prompt(),
            user,
            schema,
            self._fast_model,
            match_id=candidates[0].match_id,
        )
        result = DetectorResponse.model_validate(payload)
        expected = {candidate.moment_id for candidate in candidates}
        actual = [decision.moment_id for decision in result.decisions]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            missing = sorted(expected - set(actual))
            unknown = sorted(set(actual) - expected)
            raise ValueError(
                "detector must return exactly one decision per candidate; "
                f"expected={len(expected)}, received={len(actual)}, "
                f"unique={len(set(actual))}, missing={missing}, unknown={unknown}"
            )
        return result

    def _apply_decisions(
        self, candidates: list[Moment], response: DetectorResponse
    ) -> list[Moment]:
        by_id = {candidate.moment_id: candidate for candidate in candidates}
        decisions = {decision.moment_id: decision for decision in response.decisions}
        kept = {
            moment_id: candidate.model_copy(
                update={"significance": decisions[moment_id].significance, "source": "agent"}
            )
            for moment_id, candidate in by_id.items()
            if decisions[moment_id].keep
        }
        grouped_ids: set[str] = set()
        for group in response.merge_groups:
            group_ids = set(group)
            if (
                len(group) < 2
                or len(group_ids) != len(group)
                or not group_ids <= kept.keys()
                or group_ids & grouped_ids
            ):
                raise ValueError("detector returned an invalid merge group")
            group_candidates = [kept[moment_id] for moment_id in group]
            if len(merge_candidates(group_candidates)) != 1:
                raise ValueError("detector returned incompatible merge candidates")
            combined = merge_candidates(group_candidates)[0]
            combined = combined.model_copy(
                update={
                    "significance": max(item.significance for item in group_candidates),
                    "source": "agent",
                }
            )
            for moment_id in group:
                del kept[moment_id]
            kept[combined.moment_id] = combined
            grouped_ids.update(group_ids)
        return sorted(kept.values(), key=lambda item: (item.seq_start, item.moment_id))

    def _limit_noncritical(
        self,
        candidates: list[Moment],
        elapsed_ms: int,
        *,
        include_deferred: bool = True,
    ) -> list[Moment]:
        eligible = [candidate for candidate in candidates if candidate.type not in CRITICAL_TYPES]
        if include_deferred and self._deferred is not None:
            eligible.append(self._deferred)
        if (
            self._last_noncritical_ms is not None
            and elapsed_ms - self._last_noncritical_ms < NONCRITICAL_INTERVAL_MS
        ):
            if eligible:
                self._deferred = max(
                    eligible,
                    key=lambda item: (item.significance, item.rule_score, -item.seq_start),
                )
            return []
        if not eligible:
            return []
        selected = max(
            eligible,
            key=lambda item: (item.significance, item.rule_score, -item.seq_start, item.moment_id),
        )
        self._deferred = None
        self._last_noncritical_ms = elapsed_ms
        return [selected]


def _fallback(candidates: list[Moment]) -> list[Moment]:
    return [
        candidate.model_copy(update={"significance": candidate.rule_score, "source": "fallback"})
        for candidate in candidates
    ]


def _system_prompt() -> str:
    return files("matchlens.agents").joinpath("prompts/detector.md").read_text(encoding="utf-8")
