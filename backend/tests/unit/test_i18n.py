from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from matchlens.agents.verifier import verify_claims
from matchlens.i18n import fallback_text
from matchlens.models.clock import MatchClock
from matchlens.models.insights import Insight, Moment, MomentType
from matchlens.store.memory import MemoryMetricStore

if TYPE_CHECKING:
    from matchlens.models.base import Language

_MOMENT_TYPES: tuple[MomentType, ...] = (
    "goal",
    "big_chance",
    "card",
    "momentum_swing",
    "press_shift",
    "control_shift",
    "milestone",
    "speed_alert",
    "player_spotlight",
)


@pytest.mark.parametrize("language", ["en", "es"])
@pytest.mark.parametrize("moment_type", _MOMENT_TYPES)
def test_fallback_templates_are_localized_and_pass_number_verification(
    language: Language, moment_type: MomentType
) -> None:
    headline, body = fallback_text(language, moment_type)
    moment = Moment(
        moment_id="fallback-moment",
        match_id="fallback-match",
        type=moment_type,
        seq_start=1,
        seq_end=1,
        clock=MatchClock(period=1, ms=0),
        rule_score=0.5,
        significance=0.5,
        evidence_metric_ids=[],
        subject_ids=[],
        source="rule",
    )
    insight = Insight(
        insight_id="fallback-insight",
        moment_id=moment.moment_id,
        headline=headline,
        body=body,
        claims=[],
        tags=[],
        status="verified",
        attempts=0,
        errors=[],
    )

    errors = asyncio.run(verify_claims(insight, moment, MemoryMetricStore(), language))

    assert headline
    assert body
    assert errors == []
