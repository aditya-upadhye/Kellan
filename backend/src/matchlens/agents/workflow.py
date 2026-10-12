import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Never

from agent_framework import Workflow, WorkflowBuilder, WorkflowContext, executor

from matchlens.agents.detector import DetectorAgent
from matchlens.agents.evidence import moment_evidence
from matchlens.agents.explainer import ExplainerAgent
from matchlens.agents.fact_checker import FactCheckerAgent
from matchlens.agents.personalizer import (
    PersonalizationContext,
    PersonalizedContent,
    PersonalizerAgent,
)
from matchlens.agents.producer import priority_for
from matchlens.agents.verifier import verify_claims
from matchlens.config import Settings
from matchlens.llm.runtime import RuntimeLLMClient
from matchlens.models.base import TeamSide
from matchlens.models.clock import MatchClock
from matchlens.models.cues import CheckerResult, CueProvenance, OverlayCue
from matchlens.models.insights import Insight, Moment
from matchlens.models.match import MatchMetadata
from matchlens.models.profiles import ViewerProfile
from matchlens.models.traces import AgentTrace
from matchlens.store.base import MetricStore


@dataclass(frozen=True, slots=True)
class DetectionRequest:
    candidates: list[Moment]
    elapsed_ms: int
    critical: bool = False
    flush: bool = False


@dataclass(frozen=True, slots=True)
class SelectedMoments:
    moments: tuple[Moment, ...]


@dataclass(frozen=True, slots=True)
class MomentWork:
    moment: Moment
    store: MetricStore
    score: dict[TeamSide, int]
    recent: tuple[Insight, ...] = ()


@dataclass(frozen=True, slots=True)
class VerifiedMoment:
    work: MomentWork
    insight: Insight


@dataclass(frozen=True, slots=True)
class PersonalizedMoment:
    verified: VerifiedMoment
    content: tuple[PersonalizedContent, ...]


@dataclass(frozen=True, slots=True)
class MomentResult:
    moment: Moment
    insight: Insight
    cues: tuple[OverlayCue, ...]


def selection_workflow(detector: DetectorAgent) -> Workflow:
    @executor(id="detector")
    async def select(
        request: DetectionRequest, ctx: WorkflowContext[Never, SelectedMoments]
    ) -> None:
        if request.critical:
            moments = detector.critical_moments(request.candidates)
        elif request.flush:
            moments = await detector.flush(request.elapsed_ms)
        else:
            moments = await detector.evaluate(request.candidates, {}, request.elapsed_ms)
        await ctx.yield_output(SelectedMoments(tuple(moments)))

    return WorkflowBuilder(start_executor=select).build()


@dataclass(frozen=True, slots=True)
class WorkflowServices:
    client: RuntimeLLMClient
    settings: Settings
    metadata: MatchMetadata
    profiles: tuple[ViewerProfile, ...]
    record_trace: Callable[[AgentTrace], None]


def insight_workflow(services: WorkflowServices) -> Workflow:
    settings, client = services.settings, services.client
    names = {team.team_id: team.name for team in (services.metadata.home, services.metadata.away)}
    names.update(
        {
            player.player_id: player.name
            for team in (services.metadata.home, services.metadata.away)
            for player in team.players
        }
    )
    profiles = {profile.profile_id: profile for profile in services.profiles}

    @executor(id="explainer_fact_checker")
    async def explain(work: MomentWork, ctx: WorkflowContext[VerifiedMoment]) -> None:
        checker = FactCheckerAgent(
            ExplainerAgent(client, settings.strong_model or "mock-strong"),
            work.store,
            services.record_trace,
            fault_inject_rate=settings.fault_inject_rate,
        )
        insight = await checker.create_insight(
            work.moment,
            await moment_evidence(work.moment, work.store),
            work.score,
            names,
            list(work.recent),
        )
        if insight.status not in {"verified", "fallback"} or await verify_claims(
            insight, work.moment, work.store
        ):
            raise ValueError("workflow cannot publish an unverified insight")
        await ctx.send_message(VerifiedMoment(work, insight))

    @executor(id="personalizer")
    async def personalize(
        verified: VerifiedMoment, ctx: WorkflowContext[PersonalizedMoment]
    ) -> None:
        personalizer = PersonalizerAgent(
            client, settings.fast_model or "mock-fast", services.record_trace
        )
        context = PersonalizationContext(verified.work.moment, verified.work.store, names)
        content = await asyncio.gather(
            *(
                personalizer.personalize(
                    verified.insight, profile, verified.insight.claims, context
                )
                for profile in services.profiles
            )
        )
        await ctx.send_message(
            PersonalizedMoment(verified, tuple(item for item in content if item is not None))
        )

    @executor(id="producer")
    async def produce(
        personalized: PersonalizedMoment, ctx: WorkflowContext[Never, MomentResult]
    ) -> None:
        verified = personalized.verified
        moment = verified.work.moment
        cues: list[OverlayCue] = []
        for content in personalized.content:
            profile = profiles[content.profile_id]
            candidate = verified.insight.model_copy(
                update={
                    "headline": content.headline,
                    "body": content.body,
                    "claims": list(content.claims),
                }
            )
            if await verify_claims(candidate, moment, verified.work.store, profile.language):
                raise ValueError("workflow cannot publish unverified personalized content")
            cues.append(_cue(moment, content, profile, verified.insight, services))
        await ctx.yield_output(MomentResult(moment, verified.insight, tuple(cues)))

    # https://learn.microsoft.com/en-us/agent-framework/get-started/workflows
    return (
        WorkflowBuilder(start_executor=explain)
        .add_edge(explain, personalize)
        .add_edge(personalize, produce)
        .build()
    )


def _cue(
    moment: Moment,
    content: PersonalizedContent,
    profile: ViewerProfile,
    insight: Insight,
    services: WorkflowServices,
) -> OverlayCue:
    favorite_subjects = {profile.favorite_player_id, profile.favorite_team_id} - {None}
    if profile.favorite_team_id is not None:
        team = getattr(services.metadata, profile.favorite_team_id)
        favorite_subjects.update(player.player_id for player in team.players)
    digest = sha256(f"{moment.moment_id}:{profile.profile_id}".encode()).hexdigest()[:32]
    return OverlayCue(
        cue_id=f"cue-{digest}",
        match_id=moment.match_id,
        profile_id=profile.profile_id,
        insight_id=insight.insight_id,
        trigger_seq=moment.seq_end,
        clock=moment.clock,
        template=content.template,
        slot=content.slot,
        priority=priority_for(
            moment.significance, bool(favorite_subjects.intersection(moment.subject_ids))
        ),
        start_delay_ms=0,
        duration_ms=5_000,
        expires_at=MatchClock(period=moment.clock.period, ms=moment.clock.ms + 60_000),
        headline=content.headline,
        body=content.body,
        language=profile.language,
        data={
            "moment_id": moment.moment_id,
            "moment_type": moment.type,
            "status": "fallback" if "fallback" in (insight.status, content.status) else "verified",
            "claims": [claim.model_dump(mode="json") for claim in content.claims],
        },
        provenance=CueProvenance(
            metric_ids=sorted({claim.metric_id for claim in content.claims}),
            checker=CheckerResult(
                passed=True,
                attempts=insight.attempts + content.attempts,
                version="deterministic-v1",
            ),
            model_ids=sorted(services.client.models_used.get(moment.moment_id, set())),
        ),
    )
