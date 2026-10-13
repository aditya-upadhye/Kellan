from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest

from matchlens.agents.personalizer import (
    PersonalizationContext,
    PersonalizerAgent,
)
from matchlens.llm.client import MockLLMClient, MockResponse
from matchlens.models.clock import MatchClock
from matchlens.models.insights import Claim, Insight, Moment
from matchlens.models.metrics import MetricSnapshot
from matchlens.profiles import DEFAULT_PROFILES
from matchlens.store.memory import MemoryMetricStore

if TYPE_CHECKING:
    from matchlens.agents.personalizer import PersonalizedContent
    from matchlens.models.profiles import ViewerProfile


def moment() -> Moment:
    return Moment(
        moment_id="personalizer-goal",
        match_id="personalizer-match",
        type="goal",
        seq_start=10,
        seq_end=10,
        clock=MatchClock(period=1, ms=10_000),
        rule_score=1.0,
        significance=1.0,
        evidence_metric_ids=["team.home.xg"],
        subject_ids=["home", "h09"],
        source="rule",
    )


def snapshot() -> MetricSnapshot:
    return MetricSnapshot(
        metric_id="team.home.xg",
        scope="team",
        subject_id="home",
        label="Expected goals",
        value=0.7,
        unit="xG",
        window="match",
        as_of_seq=10,
        clock=MatchClock(period=1, ms=10_000),
    )


def source_insight() -> Insight:
    claim = Claim(
        claim_id="source-c1",
        text_span="0.70 xG",
        metric_id="team.home.xg",
        value=0.7,
        as_of_seq=10,
    )
    return Insight(
        insight_id="source-insight",
        moment_id=moment().moment_id,
        headline="Kestrel create a clear opening",
        body="Expected goals reach 0.70 xG.",
        claims=[claim],
        tags=["chance"],
        status="verified",
        attempts=1,
        errors=[],
    )


def run_personalizer(
    response: MockResponse,
    profile: ViewerProfile = DEFAULT_PROFILES[0],
    *,
    selected_moment: Moment | None = None,
    names: dict[str, str] | None = None,
) -> PersonalizedContent | None:
    store = MemoryMetricStore()
    selected_moment = selected_moment or moment()

    async def run() -> PersonalizedContent | None:
        await store.put(selected_moment.match_id, snapshot())
        client = MockLLMClient({("personalizer", "goal"): response})
        agent = PersonalizerAgent(client, "fast")
        return await agent.personalize(
            source_insight(),
            profile,
            source_insight().claims,
            PersonalizationContext(
                moment=selected_moment,
                store=store,
                subject_names=names or {"home": "Kestrel Bay Athletic", "h09": "Dario Kestell"},
            ),
        )

    return asyncio.run(run())


def response_for(user: str) -> dict[str, Any]:
    profile_id = json.loads(user)["profile"]["profile_id"]
    if profile_id == "casual_en":
        return {
            "headline": "A dangerous opening for Kestrel",
            "body": [{"text": "The home side creates a clear chance.", "claim_key": None}],
        }
    return {
        "headline": "Kestrel's chance carries quality",
        "body": [{"text": "The chance is valued at ", "claim_key": "A"}],
    }


def test_personalized_content_is_reverified_and_presentation_varies_by_profile() -> None:
    analyst = run_personalizer(response_for)
    casual = run_personalizer(response_for, DEFAULT_PROFILES[1])

    assert analyst is not None
    assert analyst.body == "The chance is valued at 0.70 xG"
    assert analyst.claims == tuple(source_insight().claims)
    assert analyst.status == "verified"
    assert (analyst.template, analyst.slot) == ("stat_bar", "side_panel")
    assert casual is not None
    assert casual.body == "The home side creates a clear chance."
    assert casual.claims == ()
    assert len(casual.body) <= 140
    assert (casual.template, casual.slot) == ("moment_card", "lower_third")


def test_personalizer_retries_uncited_numbers_and_supplies_error_feedback() -> None:
    requests: list[dict[str, Any]] = []

    def respond(user: str) -> dict[str, Any]:
        request = json.loads(user)
        requests.append(request)
        if len(requests) == 1:
            return {
                "headline": "Two chances emerge",
                "body": [{"text": "The attack looks dangerous.", "claim_key": None}],
            }
        return response_for(user)

    personalized = run_personalizer(respond)

    assert personalized is not None
    assert personalized.attempts == 2
    assert requests[1]["check_errors"][0]["code"] == "uncited_number"
    assert requests[1]["previous_draft"]["headline"] == "Two chances emerge"


def test_persistently_uncited_number_never_returns_personalized_content() -> None:
    content = run_personalizer(
        {
            "headline": "Two chances emerge",
            "body": [{"text": "A dangerous attack.", "claim_key": None}],
        }
    )

    assert content is not None
    assert content.status == "fallback"
    assert content.attempts == 3
    assert content.claims == ()
    assert "Two" not in content.headline


def test_casual_profile_retries_jargon_and_long_body() -> None:
    requests: list[dict[str, Any]] = []

    def respond(user: str) -> dict[str, Any]:
        requests.append(json.loads(user))
        if len(requests) == 1:
            return {
                "headline": "A clear opening",
                "body": [
                    {"text": "Expected goals show the chance is dangerous.", "claim_key": None}
                ],
            }
        if len(requests) == 2:
            return {
                "headline": "A clear opening",
                "body": [{"text": "A" * 141, "claim_key": None}],
            }
        return {
            "headline": "A clear opening",
            "body": [{"text": "The home side creates a clear chance.", "claim_key": None}],
        }

    personalized = run_personalizer(respond, DEFAULT_PROFILES[1])

    assert personalized is not None
    assert personalized.attempts == 3
    assert requests[1]["check_errors"][0]["detail"] == "casual profile contains jargon"
    assert requests[2]["check_errors"][0]["detail"] == "casual body exceeds 140 characters"


def test_player_focus_skips_moments_without_the_favorite_player() -> None:
    selected_moment = moment().model_copy(update={"subject_ids": ["home"]})

    personalized = run_personalizer({}, DEFAULT_PROFILES[3], selected_moment=selected_moment)

    assert personalized is None


def test_player_focus_receives_resolved_favorite_name() -> None:
    captured: list[dict[str, Any]] = []

    def respond(user: str) -> dict[str, Any]:
        request = json.loads(user)
        captured.append(request)
        return {
            "headline": "Dario leads the attack",
            "body": [{"text": "Dario Kestell creates a dangerous opening.", "claim_key": None}],
        }

    personalized = run_personalizer(respond, DEFAULT_PROFILES[3])

    assert personalized is not None
    assert captured[0]["favorite_player_name"] == "Dario Kestell"
    assert (personalized.template, personalized.slot) == ("player_tag", "top_right")


def test_spanish_profile_returns_verified_spanish_content() -> None:
    def respond(user: str) -> dict[str, Any]:
        request = json.loads(user)
        assert request["profile"]["language"] == "es"
        return {
            "headline": "Kestrel genera peligro",
            "body": [{"text": "El equipo crea una ocasión clara.", "claim_key": None}],
        }

    content = run_personalizer(respond, DEFAULT_PROFILES[2])

    assert content is not None
    assert content.status == "verified"
    assert content.headline == "Kestrel genera peligro"
    assert content.body == "El equipo crea una ocasión clara."
    assert content.claims == ()


def test_spanish_profile_preserves_the_english_source_claim_value() -> None:
    source = source_insight()
    count_claim = Claim(
        claim_id="source-count",
        text_span="2",
        metric_id="team.home.passes",
        value=2.0,
        as_of_seq=10,
    )
    source = source.model_copy(
        update={"body": "The home side completes 2 passes.", "claims": [count_claim]}
    )
    selected_moment = moment().model_copy(update={"evidence_metric_ids": ["team.home.passes"]})
    pass_snapshot = MetricSnapshot(
        metric_id="team.home.passes",
        scope="team",
        subject_id="home",
        label="Passes",
        value=2.0,
        unit="count",
        window="match",
        as_of_seq=10,
        clock=MatchClock(period=1, ms=10_000),
    )
    store = MemoryMetricStore()

    async def run() -> PersonalizedContent | None:
        await store.put(selected_moment.match_id, pass_snapshot)
        client = MockLLMClient(
            {
                ("personalizer", "goal"): {
                    "headline": "Kestrel completa pases",
                    "body": [
                        {"text": "El equipo completa", "claim_key": "A"},
                        {"text": "pases.", "claim_key": None},
                    ],
                }
            }
        )
        return await PersonalizerAgent(client, "fast").personalize(
            source,
            DEFAULT_PROFILES[2],
            source.claims,
            PersonalizationContext(
                moment=selected_moment,
                store=store,
                subject_names={"home": "Kestrel Bay Athletic"},
            ),
        )

    content = asyncio.run(run())

    assert content is not None
    assert content.status == "verified"
    assert content.body == "El equipo completa 2 pases."
    assert content.claims == (count_claim,)


def test_spanish_number_words_are_rejected_then_retried() -> None:
    requests: list[dict[str, Any]] = []

    def respond(user: str) -> dict[str, Any]:
        requests.append(json.loads(user))
        if len(requests) == 1:
            return {
                "headline": "Dos ocasiones para Kestrel",
                "body": [{"text": "El equipo genera peligro.", "claim_key": None}],
            }
        return {
            "headline": "Kestrel genera peligro",
            "body": [{"text": "El equipo crea una ocasión clara.", "claim_key": None}],
        }

    content = run_personalizer(respond, DEFAULT_PROFILES[2])

    assert content is not None
    assert content.status == "verified"
    assert content.attempts == 2
    assert requests[1]["check_errors"][0]["code"] == "uncited_number"


def test_disabled_llm_returns_localized_verified_fallback() -> None:
    content = run_personalizer({}, DEFAULT_PROFILES[2])

    assert content is not None
    assert content.status == "fallback"
    assert content.headline == "El marcador cambia"
    assert content.claims == ()


def test_personalizer_requires_verified_source_insight() -> None:
    store = MemoryMetricStore()
    insight = source_insight().model_copy(update={"status": "draft"})

    async def run() -> PersonalizedContent | None:
        await store.put(moment().match_id, snapshot())
        return await PersonalizerAgent(MockLLMClient({}), "fast").personalize(
            insight,
            DEFAULT_PROFILES[0],
            insight.claims,
            PersonalizationContext(
                moment=moment(),
                store=store,
                subject_names={"home": "Kestrel Bay Athletic"},
            ),
        )

    with pytest.raises(ValueError, match="requires a verified or checked fallback insight"):
        asyncio.run(run())
