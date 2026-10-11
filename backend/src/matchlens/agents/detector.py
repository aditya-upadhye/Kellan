from __future__ import annotations

import json
from importlib.resources import files
from typing import TYPE_CHECKING

from pydantic import Field

from matchlens.agents.triggers import merge_candidates
from matchlens.models.base import Contract

if TYPE_CHECKING:
    from collections.abc import Mapping

    from matchlens.llm.client import LLMClient
    from matchlens.models.insights import Moment

DETECTOR_INTERVAL_MS = 15_000
NONCRITICAL_INTERVAL_MS = 2 * 60_000
CRITICAL_TYPES = {"goal", "card"}


class DetectorDecision(Contract):
    moment_id: str
    keep: bool
    significance: float = Field(ge=0.0, le=1.0)


class DetectorResponse(Contract):
    decisions: list[DetectorDecision]
    merge_groups: list[list[str]]


class DetectorAgent:
    def __init__(self, client: LLMClient, fast_model: str) -> None:
        self._client = client
        self._fast_model = fast_model
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

        critical = [candidate for candidate in candidates if candidate.type in CRITICAL_TYPES]
        for candidate in candidates:
            if candidate.type not in CRITICAL_TYPES:
                self._pending[candidate.moment_id] = candidate

        if elapsed_ms < self._next_review_ms:
            return critical
        while self._next_review_ms <= elapsed_ms:
            self._next_review_ms += DETECTOR_INTERVAL_MS
        if not self._pending:
            deferred = self._limit_noncritical([], elapsed_ms)
            return sorted([*critical, *deferred], key=lambda item: (item.seq_start, item.moment_id))

        pending = list(self._pending.values())
        self._pending.clear()
        try:
            decisions = await self._request_decisions(pending, state_summary)
            reviewed = self._apply_decisions(pending, decisions)
        except Exception:
            reviewed = _fallback(pending)

        reviewed = self._limit_noncritical(reviewed, elapsed_ms)
        return sorted([*critical, *reviewed], key=lambda item: (item.seq_start, item.moment_id))

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
        payload = await self._client.complete_json(
            "detector",
            _system_prompt(),
            user,
            DetectorResponse.model_json_schema(),
            self._fast_model,
            match_id=candidates[0].match_id,
        )
        result = DetectorResponse.model_validate(payload)
        expected = {candidate.moment_id for candidate in candidates}
        actual = [decision.moment_id for decision in result.decisions]
        if len(actual) != len(set(actual)) or set(actual) != expected:
            raise ValueError("detector must return exactly one decision per candidate")
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

    def _limit_noncritical(self, candidates: list[Moment], elapsed_ms: int) -> list[Moment]:
        eligible = [candidate for candidate in candidates if candidate.type not in CRITICAL_TYPES]
        if self._deferred is not None:
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
