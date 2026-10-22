from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from string import ascii_uppercase
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from matchlens.agents.facts import join_body, render_fact
from matchlens.agents.verifier import verify_claims
from matchlens.llm.client import LLMDisabledError
from matchlens.models.base import Contract
from matchlens.models.clock import MatchClock
from matchlens.models.cues import Recap
from matchlens.models.insights import CheckError, Claim, Insight, Moment
from matchlens.models.traces import AgentTrace
from matchlens.obs.telemetry import current_trace_id

if TYPE_CHECKING:
    from collections.abc import Callable

    from matchlens.llm.client import LLMClient
    from matchlens.models.cues import RecapKind
    from matchlens.models.metrics import MetricSnapshot
    from matchlens.models.profiles import ViewerProfile
    from matchlens.store.base import MetricStore

MAX_ATTEMPTS = 2
MAX_EVIDENCE = len(ascii_uppercase)
RECAP_METRICS = (
    "team.home.goals",
    "team.away.goals",
    "team.home.possession_pct",
    "team.away.possession_pct",
    "team.home.xg",
    "team.away.xg",
    "match.control_index",
    "match.momentum",
)
MAX_MOMENT_CLAIMS = MAX_EVIDENCE - len(RECAP_METRICS)


class RecapPart(Contract):
    text: str = Field(min_length=1, max_length=240)
    evidence_key: str | None


class RecapParagraph(Contract):
    parts: list[RecapPart] = Field(min_length=1, max_length=8)


class RecapResponse(Contract):
    paragraphs: list[RecapParagraph] = Field(min_length=3, max_length=5)


@dataclass(frozen=True, slots=True)
class RecapSource:
    moment: Moment
    headline: str
    body: str
    claims: tuple[Claim, ...]


@dataclass(frozen=True, slots=True)
class _Evidence:
    key: str
    claim: Claim
    label: str
    source: str


@dataclass(frozen=True, slots=True)
class _RecapContext:
    kind: RecapKind
    profile: ViewerProfile
    sources: list[RecapSource]
    evidence: list[_Evidence]
    store: MetricStore
    recap_id: str


class RecapAgent:
    def __init__(
        self,
        client: LLMClient,
        strong_model: str,
        match_id: str,
        record_trace: Callable[[AgentTrace], None],
        request_timeout_seconds: float = 30.0,
    ) -> None:
        self._client = client
        self._strong_model = strong_model
        self._match_id = match_id
        self._record_trace = record_trace
        self._request_timeout_seconds = request_timeout_seconds

    async def create_recap(
        self,
        kind: RecapKind,
        profile: ViewerProfile,
        sources: list[RecapSource],
        snapshots: list[MetricSnapshot],
        store: MetricStore,
    ) -> Recap:
        sources = _select_sources(sources)
        recap_id = _recap_id(self._match_id, sources, profile.profile_id, kind)
        context = _RecapContext(
            kind, profile, sources, _evidence(sources, snapshots, recap_id), store, recap_id
        )
        feedback: list[dict[str, str]] = []
        previous_draft: dict[str, object] | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            started = time.perf_counter()
            try:
                payload = await asyncio.wait_for(
                    self._client.complete_json(
                        "producer",
                        _prompt(profile.language),
                        json.dumps(
                            {
                                "moment_type": "recap",
                                "kind": kind,
                                "profile": profile.model_dump(mode="json"),
                                "verified_moments": [
                                    {
                                        "type": source.moment.type,
                                        "headline": source.headline,
                                        "body": source.body,
                                        "claim_keys": [
                                            item.key
                                            for item in context.evidence
                                            if item.source == source.moment.moment_id
                                        ],
                                    }
                                    for source in sources
                                ],
                                "final_snapshots": [
                                    {
                                        "key": item.key,
                                        "metric_id": item.claim.metric_id,
                                        "label": item.label,
                                        "text_span": item.claim.text_span,
                                    }
                                    for item in context.evidence
                                    if item.source == "snapshot"
                                ],
                                "allowed_evidence": [
                                    {
                                        "key": item.key,
                                        "text_span": item.claim.text_span,
                                        "label": item.label,
                                    }
                                    for item in context.evidence
                                ],
                                "check_errors": feedback,
                                "previous_draft": previous_draft,
                            },
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                        RecapResponse.model_json_schema(),
                        self._strong_model,
                        match_id=self._match_id,
                    ),
                    timeout=self._request_timeout_seconds,
                )
                response = RecapResponse.model_validate(payload)
            except LLMDisabledError:
                self._trace(sources, "recap", "fallback", "LLM mode is off", started)
                return await self._fallback(context)
            except Exception as error:
                self._trace(sources, "recap", "error", f"{type(error).__name__}: {error}", started)
                return await self._fallback(context)

            candidate, errors = await self._candidate(response, context)
            if not errors:
                self._trace(sources, "verify", "approved", f"attempt={attempt}", started)
                return candidate.model_copy(update={"status": "verified"})

            self._trace(
                sources,
                "verify",
                "rejected",
                f"attempt={attempt}; {','.join(error.code for error in errors)}",
                started,
            )
            feedback = [{"code": error.code, "detail": error.detail} for error in errors]
            previous_draft = {
                "paragraphs": candidate.paragraphs,
                "claim_keys": [
                    item.key
                    for item in context.evidence
                    if item.claim.claim_id in {claim.claim_id for claim in candidate.claims}
                ],
            }

        self._trace(sources, "recap", "fallback", "verification retries exhausted")
        return await self._fallback(context)

    async def _candidate(
        self,
        response: RecapResponse,
        context: _RecapContext,
    ) -> tuple[Recap, list[CheckError]]:
        by_key = {item.key: item for item in context.evidence}
        used_keys: set[str] = set()
        claims: list[Claim] = []
        paragraphs: list[str] = []
        errors: list[CheckError] = []
        for paragraph in response.paragraphs:
            pieces: list[tuple[str, str | None]] = []
            for part in paragraph.parts:
                if part.evidence_key is None:
                    pieces.append((part.text, None))
                    continue
                item = by_key.get(part.evidence_key)
                if item is None or part.evidence_key in used_keys:
                    errors.append(
                        CheckError(
                            code="unsupported_claim", detail="unknown or repeated evidence key"
                        )
                    )
                    continue
                used_keys.add(part.evidence_key)
                claims.append(item.claim)
                pieces.append((part.text, item.claim.text_span))
            paragraphs.append(join_body(pieces))

        candidate = Recap(
            recap_id=context.recap_id,
            match_id=self._match_id,
            profile_id=context.profile.profile_id,
            kind=context.kind,
            title=_title(context.kind, context.profile.language),
            paragraphs=paragraphs,
            key_moment_ids=[source.moment.moment_id for source in context.sources],
            claims=claims,
            status="fallback",
        )
        errors.extend(
            await _verify(candidate, context.store, [item.claim for item in context.evidence])
        )
        return candidate, errors

    async def _fallback(self, context: _RecapContext) -> Recap:
        kind, profile, sources = context.kind, context.profile, context.sources
        paragraphs = [source.body for source in sources[:5]]
        if profile.language == "es":
            fill = (
                [
                    "El descanso cierra esta etapa del partido.",
                    "Los equipos volverán tras la pausa.",
                    "El resumen sigue los momentos verificados.",
                ]
                if kind == "half"
                else [
                    "El pitido final cierra el encuentro.",
                    "Este resumen recoge momentos verificados.",
                    "La crónica se basa en la acción registrada.",
                ]
            )
        else:
            fill = (
                [
                    "The break closes this phase of the match.",
                    "The teams return after the interval.",
                    "This recap follows verified match moments.",
                ]
                if kind == "half"
                else [
                    "The final whistle closes the contest.",
                    "This recap draws on verified match moments.",
                    "The account follows the recorded play.",
                ]
            )
        for text in fill:
            if len(paragraphs) >= 3:
                break
            paragraphs.append(text)
        claims = [claim for source in sources[:5] for claim in source.claims]
        recap = Recap(
            recap_id=context.recap_id,
            match_id=self._match_id,
            profile_id=profile.profile_id,
            kind=kind,
            title=_title(kind, profile.language),
            paragraphs=paragraphs,
            key_moment_ids=[source.moment.moment_id for source in sources[:5]],
            claims=claims,
            status="fallback",
        )
        errors = await _verify(recap, context.store, [item.claim for item in context.evidence])
        if errors:
            safe = Recap(
                recap_id=context.recap_id,
                match_id=self._match_id,
                profile_id=profile.profile_id,
                kind=kind,
                title=_title(kind, profile.language),
                paragraphs=fill,
                key_moment_ids=[],
                claims=[],
                status="fallback",
            )
            self._trace(sources, "verify", "error", "fallback failed deterministic verification")
            return safe
        self._trace(sources, "recap", "fallback", "using verified moment templates")
        return recap

    def _trace(
        self,
        sources: list[RecapSource],
        action: str,
        status: Literal["approved", "rejected", "retry", "fallback", "error"],
        detail: str,
        started: float | None = None,
    ) -> None:
        self._record_trace(
            AgentTrace(
                trace_id=current_trace_id(),
                match_id=self._match_id,
                moment_id=None,
                agent="producer",
                action=action,
                status=status,
                latency_ms=round((time.perf_counter() - started) * 1000) if started else 0,
                tokens_in=0,
                tokens_out=0,
                detail=detail[:200],
                ts=datetime.now(UTC),
            )
        )


async def _verify(
    recap: Recap, store: MetricStore, allowed_claims: list[Claim]
) -> list[CheckError]:
    claims = recap.claims
    allowed = {claim.claim_id: claim for claim in allowed_claims}
    if any(allowed.get(claim.claim_id) != claim for claim in claims):
        return [
            CheckError(code="unsupported_claim", detail="recap claim is not from verified evidence")
        ]
    latest_seq = max((claim.as_of_seq for claim in claims), default=1)
    moment = Moment(
        moment_id=recap.recap_id,
        match_id=recap.match_id,
        type="milestone",
        seq_start=1,
        seq_end=max(1, latest_seq),
        clock=MatchClock(period=1, ms=0),
        rule_score=0.3,
        significance=0.3,
        evidence_metric_ids=sorted({claim.metric_id for claim in claims}),
        subject_ids=[],
        source="fallback",
    )
    insight = Insight(
        insight_id=recap.recap_id,
        moment_id=recap.recap_id,
        headline=recap.title,
        body="\n".join(recap.paragraphs),
        claims=claims,
        tags=[],
        status="draft",
        attempts=1,
        errors=[],
    )
    return await verify_claims(insight, moment, store)


def _evidence(
    sources: list[RecapSource], snapshots: list[MetricSnapshot], recap_id: str
) -> list[_Evidence]:
    available: list[tuple[Claim, str, str]] = []
    seen_claim_ids: set[str] = set()
    represented_metrics: set[tuple[str, int, float]] = set()
    for source in sources:
        for claim in source.claims:
            if claim.claim_id not in seen_claim_ids:
                available.append((claim, claim.metric_id, source.moment.moment_id))
                seen_claim_ids.add(claim.claim_id)
                represented_metrics.add((claim.metric_id, claim.as_of_seq, claim.value))

    snapshots_by_id = {
        snapshot.metric_id: snapshot
        for snapshot in snapshots
        if snapshot.window == "match" and snapshot.metric_id in RECAP_METRICS
    }
    for metric_id in RECAP_METRICS:
        snapshot = snapshots_by_id.get(metric_id)
        if snapshot is None:
            continue
        identity = (snapshot.metric_id, snapshot.as_of_seq, snapshot.value)
        if identity in represented_metrics:
            continue
        claim = Claim(
            claim_id=f"{recap_id}-snapshot-{len(available)}",
            text_span=render_fact(snapshot),
            metric_id=snapshot.metric_id,
            value=snapshot.value,
            as_of_seq=snapshot.as_of_seq,
        )
        available.append((claim, snapshot.label, "snapshot"))
        represented_metrics.add(identity)

    result: list[_Evidence] = []
    for index, (claim, label, source) in enumerate(available[:MAX_EVIDENCE]):
        result.append(_Evidence(ascii_uppercase[index], claim, label, source))
    return result


def _select_sources(sources: list[RecapSource]) -> list[RecapSource]:
    selected: list[RecapSource] = []
    claim_count = 0
    for source in sorted(
        sources,
        key=lambda item: (item.moment.significance, item.moment.seq_end),
        reverse=True,
    ):
        if len(selected) >= 5 or claim_count + len(source.claims) > MAX_MOMENT_CLAIMS:
            continue
        selected.append(source)
        claim_count += len(source.claims)
    return selected


def _recap_id(match_id: str, sources: list[RecapSource], profile_id: str, kind: RecapKind) -> str:
    final_seq = max((source.moment.seq_end for source in sources), default=0)
    digest = hashlib.sha256(f"{match_id}:{profile_id}:{kind}:{final_seq}".encode()).hexdigest()[:24]
    return f"recap-{digest}"


def _title(kind: RecapKind, language: str) -> str:
    if language == "es":
        return "Resumen del descanso" if kind == "half" else "Resumen final"
    return "Halftime recap" if kind == "half" else "Full-time recap"


def _prompt(language: str) -> str:
    filename = "recap.es.md" if language == "es" else "recap.md"
    return files("matchlens.agents").joinpath(f"prompts/{filename}").read_text(encoding="utf-8")
