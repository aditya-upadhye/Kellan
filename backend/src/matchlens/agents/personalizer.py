from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from string import ascii_uppercase
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from matchlens.agents.facts import join_body
from matchlens.agents.verifier import verify_claims
from matchlens.llm.client import LLMDisabledError
from matchlens.models.base import Contract
from matchlens.models.insights import CheckError
from matchlens.models.traces import AgentTrace
from matchlens.obs.telemetry import current_trace_id

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from matchlens.llm.client import LLMClient
    from matchlens.models.cues import CueSlot, CueTemplate
    from matchlens.models.insights import Claim, Insight, Moment
    from matchlens.models.profiles import ViewerProfile
    from matchlens.store.base import MetricStore

MAX_ATTEMPTS = 3
CASUAL_BODY_LIMIT = 140
_PRESENTATION: dict[str, tuple[CueTemplate, CueSlot]] = {
    "analyst": ("stat_bar", "side_panel"),
    "casual": ("moment_card", "lower_third"),
    "player_focus": ("player_tag", "top_right"),
}
_CASUAL_JARGON = re.compile(
    r"\b(?:xG|PPDA|expected goals|possession|control index|momentum index|"
    r"pass completion|pressing efficiency)\b",
    re.IGNORECASE,
)


class PersonalizerPart(Contract):
    text: str = Field(min_length=1)
    claim_key: str | None


class PersonalizerResponse(Contract):
    headline: str = Field(min_length=1, max_length=60)
    body: list[PersonalizerPart] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class PersonalizedContent:
    profile_id: str
    insight_id: str
    moment_id: str
    headline: str
    body: str
    claims: tuple[Claim, ...]
    template: CueTemplate
    slot: CueSlot
    attempts: int
    status: Literal["verified"] = "verified"


@dataclass(frozen=True, slots=True)
class PersonalizationContext:
    moment: Moment
    store: MetricStore
    subject_names: Mapping[str, str]


class PersonalizationRejectedError(RuntimeError):
    def __init__(self, errors: list[CheckError], attempts: int) -> None:
        self.errors = tuple(errors)
        self.attempts = attempts
        super().__init__("personalized text failed deterministic verification")


class PersonalizerAgent:
    def __init__(
        self,
        client: LLMClient,
        fast_model: str,
        record_trace: Callable[[AgentTrace], None] | None = None,
    ) -> None:
        self._client = client
        self._fast_model = fast_model
        self._record_trace = record_trace

    async def personalize(
        self,
        insight: Insight,
        profile: ViewerProfile,
        allowed_claims: list[Claim],
        context: PersonalizationContext,
    ) -> PersonalizedContent | None:
        moment = context.moment
        store = context.store
        subject_names = context.subject_names
        if insight.status != "verified":
            raise ValueError("Personalizer requires a verified insight")
        if insight.moment_id != moment.moment_id:
            raise ValueError("insight and moment IDs must match")
        if profile.language != "en":
            raise ValueError(
                "Personalizer supports English until M6 number-word verification is added"
            )
        if profile.mode == "player_focus":
            favorite_player_id = profile.favorite_player_id
            if favorite_player_id not in moment.subject_ids:
                self._record(moment, "personalize", "fallback", "favorite player is not involved")
                return None
            if favorite_player_id not in subject_names:
                raise ValueError("player-focus profile requires the favorite player's display name")

        source_errors = await verify_claims(insight, moment, store)
        if source_errors:
            raise ValueError("source insight must pass verification before personalization")
        claims_by_key = self._allowed_claims(insight, allowed_claims)
        user = self._user_payload(insight, profile, claims_by_key, moment, subject_names)
        feedback: list[dict[str, str]] = []
        previous_draft: dict[str, object] | None = None
        errors: list[CheckError] = []

        for attempt in range(1, MAX_ATTEMPTS + 1):
            started = time.perf_counter()
            try:
                payload = await self._client.complete_json(
                    "personalizer",
                    files("matchlens.agents")
                    .joinpath("prompts/personalizer.md")
                    .read_text(encoding="utf-8"),
                    json.dumps(
                        {
                            **user,
                            "check_errors": feedback,
                            "previous_draft": previous_draft,
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    PersonalizerResponse.model_json_schema(),
                    self._fast_model,
                    match_id=moment.match_id,
                    moment_id=moment.moment_id,
                )
                response = PersonalizerResponse.model_validate(payload)
            except LLMDisabledError:
                self._record(moment, "personalize", "fallback", "LLM mode is off", started)
                raise
            except Exception as error:
                self._record(moment, "personalize", "error", type(error).__name__, started)
                raise RuntimeError("Personalizer could not produce structured output") from error

            candidate, selected_claims, errors = self._candidate(
                insight, profile, response, claims_by_key
            )
            errors.extend(await verify_claims(candidate, moment, store))
            if not errors:
                self._record(moment, "verify", "approved", f"attempt={attempt}", started)
                template, slot = _PRESENTATION[profile.mode]
                return PersonalizedContent(
                    profile_id=profile.profile_id,
                    insight_id=insight.insight_id,
                    moment_id=moment.moment_id,
                    headline=candidate.headline,
                    body=candidate.body,
                    claims=tuple(selected_claims),
                    template=template,
                    slot=slot,
                    attempts=attempt,
                )

            self._record(
                moment,
                "verify",
                "rejected",
                f"attempt={attempt}; {','.join(error.code for error in errors)}",
                started,
            )
            feedback = [{"code": error.code, "detail": error.detail} for error in errors]
            previous_draft = {
                "headline": candidate.headline,
                "body": candidate.body,
                "claim_keys": [
                    key
                    for key, claim in claims_by_key.items()
                    if claim.claim_id in {selected.claim_id for selected in selected_claims}
                ],
            }
            if attempt < MAX_ATTEMPTS:
                self._record(moment, "revise", "retry", f"attempt={attempt + 1}")

        raise PersonalizationRejectedError(errors, MAX_ATTEMPTS)

    @staticmethod
    def _allowed_claims(insight: Insight, allowed_claims: list[Claim]) -> dict[str, Claim]:
        source = {claim.claim_id: claim for claim in insight.claims}
        if len(allowed_claims) > len(ascii_uppercase):
            raise ValueError("too many allowed claims")
        if len({claim.claim_id for claim in allowed_claims}) != len(allowed_claims):
            raise ValueError("allowed claims must have unique IDs")
        if any(source.get(claim.claim_id) != claim for claim in allowed_claims):
            raise ValueError("allowed claims must come from the verified insight")
        return {ascii_uppercase[index]: claim for index, claim in enumerate(allowed_claims)}

    @staticmethod
    def _user_payload(
        insight: Insight,
        profile: ViewerProfile,
        claims_by_key: Mapping[str, Claim],
        moment: Moment,
        subject_names: Mapping[str, str],
    ) -> dict[str, object]:
        favorite_id = profile.favorite_player_id
        return {
            "moment_type": moment.type,
            "profile": profile.model_dump(mode="json"),
            "favorite_player_name": subject_names.get(favorite_id) if favorite_id else None,
            "moment_subject_names": [
                subject_names[subject] for subject in moment.subject_ids if subject in subject_names
            ],
            "verified_insight": {
                "headline": insight.headline,
                "body": insight.body,
                "tags": insight.tags,
            },
            "allowed_claims": [
                {"key": key, "text_span": claim.text_span} for key, claim in claims_by_key.items()
            ],
        }

    @staticmethod
    def _candidate(
        insight: Insight,
        profile: ViewerProfile,
        response: PersonalizerResponse,
        claims_by_key: Mapping[str, Claim],
    ) -> tuple[Insight, list[Claim], list[CheckError]]:
        pieces: list[tuple[str, str | None]] = []
        selected_claims: list[Claim] = []
        errors: list[CheckError] = []
        used_keys: set[str] = set()
        for part in response.body:
            if part.claim_key is None:
                pieces.append((part.text, None))
                continue
            claim = claims_by_key.get(part.claim_key)
            if claim is None or part.claim_key in used_keys:
                errors.append(
                    CheckError(code="unsupported_claim", detail="unknown or repeated claim key")
                )
                continue
            used_keys.add(part.claim_key)
            selected_claims.append(claim)
            pieces.append((part.text, claim.text_span))

        body = join_body(pieces)
        candidate = insight.model_copy(
            update={
                "headline": response.headline,
                "body": body,
                "claims": selected_claims,
            }
        )
        if profile.mode == "casual":
            if len(body) > CASUAL_BODY_LIMIT:
                errors.append(
                    CheckError(code="too_long", detail="casual body exceeds 140 characters")
                )
            if _CASUAL_JARGON.search(f"{response.headline} {body}"):
                errors.append(
                    CheckError(code="unsupported_claim", detail="casual profile contains jargon")
                )
        return candidate, selected_claims, errors

    def _record(
        self,
        moment: Moment,
        action: str,
        status: Literal["approved", "rejected", "retry", "fallback", "error"],
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
                agent="personalizer",
                action=action,
                status=status,
                latency_ms=round((time.perf_counter() - started) * 1000) if started else 0,
                tokens_in=0,
                tokens_out=0,
                detail=detail[:200],
                ts=datetime.now(UTC),
            )
        )
