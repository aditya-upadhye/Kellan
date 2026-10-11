from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from matchlens.agents.verifier import verify_claims
from matchlens.models.clock import MatchClock
from matchlens.models.insights import Claim, Insight, Moment
from matchlens.models.metrics import MetricSnapshot
from matchlens.store.memory import MemoryMetricStore

if TYPE_CHECKING:
    from matchlens.models.insights import CheckError
    from matchlens.models.metrics import MetricUnit


MATCH_ID = "verifier-match"
XG = "team.home.xg"
PASSES = "team.home.passes"
SPEED = "player.h09.top_speed_kmh"
AWAY_XG = "team.away.xg"


def snapshot(
    metric_id: str, value: float, seq: int = 10, unit: MetricUnit = "xG"
) -> MetricSnapshot:
    scope, subject_id, *_ = metric_id.split(".")
    return MetricSnapshot.model_validate(
        {
            "metric_id": metric_id,
            "scope": scope,
            "subject_id": subject_id,
            "label": "Test metric",
            "value": value,
            "unit": unit,
            "window": "match",
            "as_of_seq": seq,
            "clock": {"period": 1, "ms": seq * 1000},
        }
    )


def moment(evidence: list[str] | None = None) -> Moment:
    return Moment(
        moment_id="verifier-moment",
        match_id=MATCH_ID,
        type="milestone",
        seq_start=20,
        seq_end=20,
        clock=MatchClock(period=1, ms=20_000),
        rule_score=0.3,
        significance=0.3,
        evidence_metric_ids=[XG, PASSES, SPEED] if evidence is None else evidence,
        subject_ids=["home"],
        source="rule",
    )


def claim(text_span: str, metric_id: str = XG, value: float = 1.42, seq: int = 10) -> Claim:
    return Claim(
        claim_id="claim-1",
        text_span=text_span,
        metric_id=metric_id,
        value=value,
        as_of_seq=seq,
    )


def insight(body: str, claims: list[Claim], headline: str = "Pressure builds") -> Insight:
    return Insight(
        insight_id="insight-1",
        moment_id="verifier-moment",
        headline=headline,
        body=body,
        claims=claims,
        tags=[],
        status="draft",
        attempts=1,
        errors=[],
    )


def check(
    draft: Insight,
    snapshots: list[MetricSnapshot],
    selected: Moment | None = None,
) -> list[CheckError]:
    async def run() -> list[CheckError]:
        store = MemoryMetricStore()
        for item in snapshots:
            await store.put(MATCH_ID, item)
        return await verify_claims(draft, selected or moment(), store)

    return asyncio.run(run())


def test_accepts_rounded_claim_from_historical_snapshot() -> None:
    draft = insight("Their xG reaches 1.4 xG.", [claim("1.4 xG")])

    assert check(draft, [snapshot(XG, 1.42, 10), snapshot(XG, 2.1, 20)]) == []


@pytest.mark.parametrize(
    ("words", "value"),
    [("two", 2), ("twenty-one", 21), ("one hundred and five", 105), ("first", 1)],
)
def test_number_words_are_supported_when_cited(words: str, value: int) -> None:
    draft = insight(f"They complete {words} passes.", [claim(words, PASSES, value)])

    assert check(draft, [snapshot(PASSES, value, unit="count")]) == []


def test_number_word_with_unit_must_match_metric_unit() -> None:
    draft = insight("He reaches thirty-four km/h.", [claim("thirty-four km/h", SPEED, 34)])

    assert check(draft, [snapshot(SPEED, 34, unit="km/h")]) == []


def test_unknown_metric_is_reported() -> None:
    draft = insight("Away xG reaches 1.4 xG.", [claim("1.4 xG", AWAY_XG)])

    errors = check(draft, [], moment([AWAY_XG]))

    assert [error.code for error in errors] == ["unknown_metric"]


def test_claim_value_must_match_historical_metric_and_displayed_precision() -> None:
    draft = insight("Their xG reaches 1.4 xG.", [claim("1.4 xG", value=1.8)])

    errors = check(draft, [snapshot(XG, 1.42)])

    assert [error.code for error in errors] == ["value_mismatch"]


def test_missing_text_span_is_reported() -> None:
    draft = insight("Pressure keeps building.", [claim("1.4 xG")])

    errors = check(draft, [snapshot(XG, 1.42)])

    assert [error.code for error in errors] == ["span_not_found"]


@pytest.mark.parametrize("unsupported", ["evidence", "unit", "future", "span"])
def test_unsupported_claims_are_reported(unsupported: str) -> None:
    cases = {
        "evidence": (
            insight("Away xG reaches 1.4 xG.", [claim("1.4 xG", AWAY_XG)]),
            [snapshot(AWAY_XG, 1.42)],
        ),
        "unit": (
            insight("His speed reaches 34%.", [claim("34%", SPEED, 34)]),
            [snapshot(SPEED, 34, unit="km/h")],
        ),
        "future": (
            insight("Their xG reaches 1.4 xG.", [claim("1.4 xG", seq=21)]),
            [snapshot(XG, 1.42)],
        ),
        "span": (
            insight(
                "Their xG reaches 1.4 xG after 2 shots.",
                [claim("Their xG reaches 1.4 xG after 2 shots")],
            ),
            [snapshot(XG, 1.42)],
        ),
    }
    draft, snapshots = cases[unsupported]
    selected = moment([XG]) if unsupported == "evidence" else None

    errors = check(draft, snapshots, selected)

    assert [error.code for error in errors] == ["unsupported_claim"]


def test_digits_units_and_number_words_without_claims_are_reported() -> None:
    draft = insight("Two chances and a 34 km/h sprint in the 70th minute.", [])

    errors = check(draft, [])

    assert [error.code for error in errors] == ["uncited_number"] * 3
    assert errors[0].detail.startswith("Two")
    assert errors[1].detail.startswith("34 km/h")
    assert errors[2].detail.startswith("70th")


def test_headline_and_body_limits_are_reported() -> None:
    draft = insight("B" * 281, [], headline="A" * 61)

    errors = check(draft, [])

    assert [error.code for error in errors] == ["too_long", "too_long"]
