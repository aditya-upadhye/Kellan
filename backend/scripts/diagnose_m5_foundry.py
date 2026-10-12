from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
from typing import TYPE_CHECKING

from matchlens.agents.evidence import moment_evidence
from matchlens.agents.explainer import ExplainerAgent, ExplainerResponse
from matchlens.agents.fact_checker import FactCheckerAgent
from matchlens.agents.triggers import RuleTriggerEngine
from matchlens.agents.verifier import verify_draft
from matchlens.config import LLMMode, Settings
from matchlens.llm.client import create_llm_client
from matchlens.metrics.engine import MetricsEngine
from matchlens.models.events import GoalEvent
from matchlens.models.tracking import TrackingFrame
from matchlens.sim.match import simulate_scenario
from matchlens.sim.scenarios import load_scenario
from matchlens.store.memory import MemoryMetricStore
from matchlens.world.meridian import MERIDIAN_LEAGUE

if TYPE_CHECKING:
    from matchlens.models.base import TeamSide
    from matchlens.models.insights import CheckError, Moment
    from matchlens.models.metrics import MetricSnapshot
    from matchlens.models.traces import AgentTrace


@dataclass(frozen=True, slots=True)
class DiagnosticOptions:
    max_moments: int
    distinct_types: bool
    moment_types: set[str] | None
    scenario_name: str
    seed: int
    moment_id: str | None
    retries: bool


@dataclass(slots=True)
class DiagnosticState:
    store: MemoryMetricStore
    score: dict[TeamSide, int]
    names: dict[str, str]
    explainer: ExplainerAgent
    checker: FactCheckerAgent
    traces: list[AgentTrace]
    drafts: list[dict[str, object]]


async def inspect_moment(
    moment: Moment, available: list[MetricSnapshot], state: DiagnosticState, retries: bool
) -> tuple[dict[str, object], list[CheckError]]:
    result: dict[str, object] = {
        "moment_type": moment.type,
        "moment_id": moment.moment_id,
        "evidence": [
            {
                "metric_id": snapshot.metric_id,
                "value": snapshot.value,
                "unit": snapshot.unit,
            }
            for snapshot in available
        ],
    }
    if retries:
        trace_start = len(state.traces)
        draft_start = len(state.drafts)
        insight = await state.checker.create_insight(
            moment, available, state.score, state.names, []
        )
        errors = await verify_draft(
            insight, moment, [] if insight.status == "fallback" else available, state.store
        )
        result.update(
            {
                "insight": insight.model_dump(mode="json"),
                "check_errors": [error.model_dump(mode="json") for error in errors],
                "traces": [
                    {"action": trace.action, "status": trace.status, "detail": trace.detail}
                    for trace in state.traces[trace_start:]
                ],
                "draft_attempts": state.drafts[draft_start:],
            }
        )
        return result, errors
    try:
        draft = await state.explainer.explain(moment, available, state.score, state.names, [])
        errors = await verify_draft(draft, moment, available, state.store)
    except Exception as error:
        result.update({"draft": None, "draft_error": type(error).__name__, "check_errors": []})
        return result, []
    result.update(
        {
            "draft": draft.model_dump(mode="json"),
            "check_errors": [error.model_dump(mode="json") for error in errors],
        }
    )
    return result, errors


async def main(options: DiagnosticOptions) -> None:
    if options.max_moments < 1:
        raise ValueError("max_moments must be positive")
    settings = Settings(llm_mode=LLMMode.FOUNDRY)
    scenario = load_scenario(options.scenario_name, settings.scenarios_dir)
    match = simulate_scenario(MERIDIAN_LEAGUE, scenario, options.seed, with_tracking=True)
    metrics = MetricsEngine(match.metadata.match_id)
    triggers = RuleTriggerEngine(match.metadata.match_id)
    store = MemoryMetricStore()
    score: dict[TeamSide, int] = {"home": 0, "away": 0}
    names = {
        "home": match.metadata.home.name,
        "away": match.metadata.away.name,
        **{
            player.player_id: player.name
            for team in (match.metadata.home, match.metadata.away)
            for player in team.players
        },
    }
    inputs = sorted(
        [*match.events, *match.frames],
        key=lambda item: (item.clock.period, item.clock.ms, isinstance(item, TrackingFrame)),
    )
    explainer = ExplainerAgent(create_llm_client(settings), settings.strong_model or "")
    traces: list[AgentTrace] = []
    drafts: list[dict[str, object]] = []
    checker = FactCheckerAgent(
        explainer,
        store,
        traces.append,
        fault_inject_rate=0.0,
        record_draft=lambda draft, errors: drafts.append(
            {
                "draft": draft.model_dump(mode="json"),
                "check_errors": [error.model_dump(mode="json") for error in errors],
            }
        ),
    )
    state = DiagnosticState(store, score, names, explainer, checker, traces, drafts)
    seen_types: set[str] = set()
    results: list[dict[str, object]] = []
    errors_found: list[CheckError] = []
    for item in inputs:
        snapshots = (
            metrics.consume_frame(item)
            if isinstance(item, TrackingFrame)
            else metrics.consume_event(item)
        )
        for snapshot in snapshots:
            await store.put(match.metadata.match_id, snapshot)
        if isinstance(item, GoalEvent):
            score[item.team_id] += 1
        for moment in triggers.consume(item, snapshots):
            if options.moment_types is not None and moment.type not in options.moment_types:
                continue
            if options.moment_id is not None and moment.moment_id != options.moment_id:
                continue
            if options.distinct_types and moment.type in seen_types:
                continue
            available = await moment_evidence(moment, store)
            seen_types.add(moment.type)
            result, errors = await inspect_moment(moment, available, state, options.retries)
            errors_found.extend(errors)
            results.append(result)
            if len(results) == options.max_moments:
                break
        if len(results) == options.max_moments:
            break
    if not results:
        raise RuntimeError("no matching moment was generated")
    codes = Counter(error.code for error in errors_found)
    draft_errors = Counter(result["draft_error"] for result in results if "draft_error" in result)
    print(
        json.dumps(
            {
                "contract": {
                    "prompt_sha": sha256(
                        files("matchlens.agents").joinpath("prompts/explainer.md").read_bytes()
                    ).hexdigest()[:12],
                    "response_fields": sorted(ExplainerResponse.model_fields),
                },
                "checked": len(results),
                "error_codes": dict(codes),
                "draft_errors": dict(draft_errors),
                "moments": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--moments", type=int, default=1)
    parser.add_argument("--distinct-types", action="store_true")
    parser.add_argument("--types", type=lambda value: set(value.split(",")))
    parser.add_argument("--scenario", default="balanced")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--moment-id")
    parser.add_argument("--retries", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        main(
            DiagnosticOptions(
                args.moments,
                args.distinct_types,
                args.types,
                args.scenario,
                args.seed,
                args.moment_id,
                args.retries,
            )
        )
    )
