from __future__ import annotations

import json
from hashlib import sha256
from importlib.resources import files
from string import ascii_uppercase
from typing import TYPE_CHECKING

from pydantic import Field

from matchlens.agents.facts import NO_EVIDENCE_CITED, join_body, render_fact
from matchlens.metrics.semantics import control_state, momentum_side
from matchlens.models.base import Contract
from matchlens.models.insights import Claim, Insight

if TYPE_CHECKING:
    from collections.abc import Mapping

    from matchlens.llm.client import LLMClient
    from matchlens.models.base import TeamSide
    from matchlens.models.insights import CheckError, Moment
    from matchlens.models.metrics import MetricSnapshot


MOMENTUM = "match.momentum"


class BodyPart(Contract):
    text: str = Field(
        description=(
            "Viewer prose. It must contain no digits, number words, ordinals, clock times or "
            "metadata; numbers come only from evidence_key."
        )
    )
    evidence_key: str | None = Field(
        description=(
            "Alphabetic key of the supplied metric whose verified value the system appends "
            "after this text, or null when no value follows."
        )
    )


class ExplainerResponse(Contract):
    headline: str = Field(min_length=1, max_length=60)
    body: list[BodyPart] = Field(min_length=1)
    tags: list[str]


def _subject_context(subject_id: str, names: Mapping[str, str]) -> dict[str, str | None]:
    if subject_id in {"home", "away"}:
        team = names.get(subject_id)
    elif subject_id.startswith("h") and subject_id[1:].isdigit():
        team = names.get("home")
    elif subject_id.startswith("a") and subject_id[1:].isdigit():
        team = names.get("away")
    else:
        team = None
    return {"name": names[subject_id], "team": team}


def _momentum_phases(
    moment: Moment, evidence_by_key: Mapping[str, MetricSnapshot]
) -> dict[str, str]:
    if moment.type != "momentum_swing":
        return {}
    keys = sorted(
        (key for key, snapshot in evidence_by_key.items() if snapshot.metric_id == MOMENTUM),
        key=lambda key: evidence_by_key[key].as_of_seq,
    )
    return {keys[0]: "start", keys[1]: "end"} if len(keys) == 2 else {}


def _momentum_context(
    evidence_by_key: Mapping[str, MetricSnapshot],
    phases: Mapping[str, str],
    names: Mapping[str, str],
) -> dict[str, object] | None:
    readings = {
        key: snapshot for key, snapshot in evidence_by_key.items() if snapshot.metric_id == MOMENTUM
    }
    home, away = names.get("home"), names.get("away")
    if not readings or home is None or away is None:
        return None
    team = {"home": home, "away": away}

    def favoured(value: float) -> str | None:
        side = momentum_side(value)
        return None if side is None else team[side]

    context: dict[str, object] = {
        "positive_favours": home,
        "negative_favours": away,
        "readings": [
            {"key": key, "favours": favoured(snapshot.value)} for key, snapshot in readings.items()
        ],
    }
    start = next((key for key, phase in phases.items() if phase == "start"), None)
    end = next((key for key, phase in phases.items() if phase == "end"), None)
    if start is not None and end is not None:
        context["change_toward"] = favoured(readings[end].value - readings[start].value)
    return context


def _evidence_item(
    key: str, snapshot: MetricSnapshot, names: Mapping[str, str], phase: str | None = None
) -> dict[str, object]:
    item: dict[str, object] = {
        "key": key,
        "label": snapshot.label,
        "value": snapshot.value,
        "unit": snapshot.unit,
        "shown_as": render_fact(snapshot),
        "subject": _subject_context(snapshot.subject_id, names)
        if snapshot.subject_id is not None and snapshot.subject_id in names
        else None,
    }
    if snapshot.metric_id == "match.control_index":
        item["state"] = control_state(snapshot.value)
    if phase is not None:
        item["phase"] = phase
    return item


def _check_feedback(error: CheckError, previous_draft: Insight | None) -> dict[str, str]:
    feedback = {"code": error.code}
    if error.code == "unsupported_claim" and error.detail == NO_EVIDENCE_CITED:
        feedback["reason"] = "evidence_required"
        return feedback
    reference = error.detail.removeprefix("unresolved evidence reference ")
    if error.code == "unsupported_claim" and reference != error.detail:
        feedback.update({"reason": "invalid_evidence_reference", "offending_text": reference})
        return feedback
    if error.code != "uncited_number" or previous_draft is None:
        return feedback
    offending_text, separator, position = error.detail.rpartition(" at position ")
    if not separator or not position.isdecimal():
        return feedback
    text = f"{previous_draft.headline}\n{previous_draft.body}"
    offset = int(position)
    if text[offset : offset + len(offending_text)] == offending_text:
        feedback["offending_text"] = offending_text
        feedback["location"] = "headline" if offset < len(previous_draft.headline) else "body"
    return feedback


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
        previous_draft: Insight | None = None,
    ) -> Insight:
        if attempt < 1:
            raise ValueError("attempt must be positive")
        if set(score) != {"home", "away"} or any(value < 0 for value in score.values()):
            raise ValueError("score must contain non-negative home and away totals")
        if any(snapshot.metric_id not in moment.evidence_metric_ids for snapshot in evidence):
            raise ValueError("evidence contains a metric outside the moment")
        if len(evidence) > len(ascii_uppercase):
            raise ValueError("too many evidence snapshots for Explainer")

        evidence_by_key = {
            ascii_uppercase[index]: snapshot for index, snapshot in enumerate(evidence)
        }
        key_by_reading = {
            (snapshot.metric_id, snapshot.as_of_seq): key
            for key, snapshot in evidence_by_key.items()
        }
        phases = _momentum_phases(moment, evidence_by_key)
        leader = None
        if score["home"] != score["away"]:
            leader = names.get("home" if score["home"] > score["away"] else "away")

        user = json.dumps(
            {
                "moment_type": moment.type,
                "evidence": [
                    _evidence_item(key, snapshot, names, phases.get(key))
                    for key, snapshot in evidence_by_key.items()
                ],
                "momentum": _momentum_context(evidence_by_key, phases, names),
                "teams": {side: names.get(side) for side in ("home", "away")},
                "subjects": [
                    _subject_context(subject, names)
                    for subject in moment.subject_ids
                    if subject in names
                ],
                "leader": leader,
                "recent_topics": [insight.tags for insight in recent_insights[-3:]],
                "check_errors": [_check_feedback(error, previous_draft) for error in errors or []],
                "previous_draft": {
                    "headline": previous_draft.headline,
                    "body": previous_draft.body,
                    "facts": [
                        {
                            "evidence_key": key_by_reading.get((claim.metric_id, claim.as_of_seq)),
                            "shown_as": claim.text_span,
                        }
                        for claim in previous_draft.claims
                    ],
                }
                if previous_draft
                else None,
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
        cited: list[MetricSnapshot] = []
        pieces: list[tuple[str, str | None]] = []
        for part in response.body:
            if part.evidence_key is None:
                pieces.append((part.text, None))
                continue
            snapshot = evidence_by_key.get(part.evidence_key)
            if snapshot is None:
                pieces.append((part.text, f"{{{part.evidence_key}}}"))
                continue
            cited.append(snapshot)
            pieces.append((part.text, render_fact(snapshot)))
        body = join_body(pieces)
        claims = [
            Claim(
                claim_id=f"{insight_id}-c{index}",
                text_span=render_fact(snapshot),
                metric_id=snapshot.metric_id,
                value=snapshot.value,
                as_of_seq=snapshot.as_of_seq,
            )
            for index, snapshot in enumerate(cited, start=1)
        ]
        return Insight(
            insight_id=insight_id,
            moment_id=moment.moment_id,
            headline=response.headline,
            body=body,
            claims=claims,
            tags=response.tags,
            status="draft",
            attempts=attempt,
            errors=[],
        )
