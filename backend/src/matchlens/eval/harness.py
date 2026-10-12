from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from statistics import mean
from typing import TYPE_CHECKING, Any

from matchlens.agents.detector import DetectorAgent
from matchlens.agents.explainer import ExplainerAgent
from matchlens.agents.fact_checker import FactCheckerAgent
from matchlens.agents.triggers import RuleTriggerEngine
from matchlens.agents.verifier import verify_claims
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
    from collections.abc import Sequence
    from pathlib import Path

    from matchlens.llm.client import MockResponse
    from matchlens.models.base import TeamSide
    from matchlens.models.insights import Insight, Moment
    from matchlens.models.match import MatchMetadata
    from matchlens.models.metrics import MetricSnapshot
    from matchlens.models.traces import AgentName, AgentTrace


def _mock_detector(user: str) -> dict[str, object]:
    candidates = json.loads(user)["candidates"]
    return {
        "decisions": [
            {
                "moment_id": candidate["moment_id"],
                "keep": True,
                "significance": candidate["rule_score"],
            }
            for candidate in candidates
        ],
        "merge_groups": [],
    }


def mock_explainer(user: str) -> dict[str, Any]:
    request = json.loads(user)
    evidence = request["evidence"]
    claims: list[dict[str, object]] = []
    if evidence:
        snapshot = evidence[0]
        value = float(snapshot["value"])
        displayed = f"{value:.4f}".rstrip("0").rstrip(".")
        suffix = f" {snapshot['unit']}" if snapshot["unit"] else ""
        span = f"{displayed}{suffix}"
        claim_value = value
        digest = sha256(request["moment"]["moment_id"].encode()).digest()
        if not request["check_errors"] and digest[0] % 10 == 0:
            claim_value += 1.0
        claims.append(
            {
                "text_span": span,
                "metric_id": snapshot["metric_id"],
                "value": claim_value,
                "as_of_seq": snapshot["as_of_seq"],
            }
        )
        body = f"A recorded metric for this moment stands at {span}."
    else:
        body = "This moment changes the course of play."
    return {
        "headline": "A match moment stands out",
        "body": body,
        "claims": claims,
        "tags": [request["moment_type"]],
    }


def _names(metadata: MatchMetadata) -> dict[str, str]:
    return {
        "home": metadata.home.name,
        "away": metadata.away.name,
        **{
            player.player_id: player.name
            for team in (metadata.home, metadata.away)
            for player in team.players
        },
    }


async def _evidence(moment: Moment, store: MemoryMetricStore) -> list[MetricSnapshot]:
    snapshots = [
        await store.get(moment.match_id, metric_id, moment.seq_end)
        for metric_id in moment.evidence_metric_ids
    ]
    return [snapshot for snapshot in snapshots if snapshot is not None]


@dataclass(slots=True)
class _EvalState:
    checker: FactCheckerAgent
    store: MemoryMetricStore
    score: dict[TeamSide, int]
    names: dict[str, str]
    recent: list[Insight]
    durations_ms: list[float]


async def _check_moments(moments: list[Moment], state: _EvalState) -> None:
    for moment in moments:
        started = time.perf_counter()
        insight = await state.checker.create_insight(
            moment,
            await _evidence(moment, state.store),
            state.score,
            state.names,
            state.recent[-3:],
        )
        state.durations_ms.append((time.perf_counter() - started) * 1000)
        errors = await verify_claims(insight, moment, state.store)
        if insight.status not in {"verified", "fallback"} or errors:
            raise RuntimeError(f"unverified insight for {moment.moment_id}: {errors}")
        state.recent.append(insight)


async def evaluate_match(
    scenario_name: str,
    seed: int,
    mode: LLMMode,
    fault_rate: float,
    settings: Settings,
) -> dict[str, Any]:
    scenario = load_scenario(scenario_name, settings.scenarios_dir)
    match = simulate_scenario(MERIDIAN_LEAGUE, scenario, seed, with_tracking=True)
    match_id = match.metadata.match_id
    metrics = MetricsEngine(match_id)
    triggers = RuleTriggerEngine(match_id)
    store = MemoryMetricStore()
    traces: list[AgentTrace] = []
    responses: dict[tuple[AgentName, str], MockResponse] | None = (
        {("detector", "batch"): _mock_detector, ("explainer", "default"): mock_explainer}
        if mode is LLMMode.MOCK
        else None
    )
    client = create_llm_client(settings, responses, traces.append)
    detector = DetectorAgent(client, settings.fast_model or "mock-fast", traces.append)
    checker = FactCheckerAgent(
        ExplainerAgent(client, settings.strong_model or "mock-strong"),
        store,
        traces.append,
        fault_inject_rate=fault_rate,
    )
    score: dict[TeamSide, int] = {"home": 0, "away": 0}
    recent: list[Insight] = []
    durations_ms: list[float] = []
    state = _EvalState(checker, store, score, _names(match.metadata), recent, durations_ms)
    inputs = sorted(
        [*match.events, *match.frames],
        key=lambda item: (item.clock.period, item.clock.ms, isinstance(item, TrackingFrame)),
    )
    for item in inputs:
        snapshots = (
            metrics.consume_frame(item)
            if isinstance(item, TrackingFrame)
            else metrics.consume_event(item)
        )
        for snapshot in snapshots:
            await store.put(match_id, snapshot)
        if isinstance(item, GoalEvent):
            score[item.team_id] += 1
        candidates = triggers.consume(item, snapshots)
        elapsed_ms = (item.clock.period - 1) * 45 * 60_000 + item.clock.ms
        moments = await detector.evaluate(candidates, {}, elapsed_ms)
        await _check_moments(moments, state)

    injections = [trace for trace in traces if trace.action == "inject"]
    caught = sum(
        any(
            trace.moment_id == injected.moment_id
            and trace.action == "verify"
            and trace.status == "rejected"
            and "value_mismatch" in trace.detail
            for trace in traces
        )
        for injected in injections
    )
    if caught != len(injections):
        raise RuntimeError(f"uncaught injected claim in {match_id}")
    calls = [trace for trace in traces if trace.action == "complete_json"]
    return {
        "scenario": scenario_name,
        "seed": seed,
        "match_id": match_id,
        "moments": len(recent),
        "verified": sum(insight.status == "verified" for insight in recent),
        "first_pass": sum(
            insight.status == "verified" and insight.attempts == 1 for insight in recent
        ),
        "fallbacks": sum(insight.status == "fallback" for insight in recent),
        "claims": sum(len(insight.claims) for insight in recent),
        "unverified_claims": 0,
        "faults_injected": len(injections),
        "faults_caught": caught,
        "llm_calls": len(calls),
        "tokens_in": sum(trace.tokens_in for trace in calls),
        "tokens_out": sum(trace.tokens_out for trace in calls),
        "insight_latency_ms": durations_ms,
        "statuses": dict(Counter(insight.status for insight in recent)),
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower), 2)


def _rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


async def evaluate(
    scenarios: Sequence[str],
    seeds: Sequence[int],
    mode: LLMMode,
    fault_rate: float,
    settings: Settings,
) -> dict[str, Any]:
    if mode not in {LLMMode.MOCK, LLMMode.FOUNDRY}:
        raise ValueError("eval supports mock or foundry mode")
    if not 0.0 <= fault_rate <= 1.0:
        raise ValueError("fault rate must be between 0 and 1")
    if not scenarios or not seeds or any(seed < 0 for seed in seeds):
        raise ValueError("provide scenarios and non-negative seeds")
    matches = [
        await evaluate_match(name, seed, mode, fault_rate, settings)
        for name in scenarios
        for seed in seeds
    ]
    totals = {
        key: sum(match[key] for match in matches)
        for key in (
            "moments",
            "verified",
            "first_pass",
            "fallbacks",
            "claims",
            "unverified_claims",
            "faults_injected",
            "faults_caught",
            "llm_calls",
            "tokens_in",
            "tokens_out",
        )
    }
    latencies = [duration for match in matches for duration in match["insight_latency_ms"]]
    for match in matches:
        match["insight_latency_p50_ms"] = _percentile(match["insight_latency_ms"], 0.5)
        match["insight_latency_p95_ms"] = _percentile(match["insight_latency_ms"], 0.95)
        del match["insight_latency_ms"]
    summary = {
        **totals,
        "matches": len(matches),
        "moments_per_match": round(mean(match["moments"] for match in matches), 2),
        "first_pass_rate": round(totals["first_pass"] / totals["moments"], 4)
        if totals["moments"]
        else None,
        "fallback_rate": round(totals["fallbacks"] / totals["moments"], 4)
        if totals["moments"]
        else None,
        "fault_catch_rate": round(totals["faults_caught"] / totals["faults_injected"], 4)
        if totals["faults_injected"]
        else None,
        "insight_latency_p50_ms": _percentile(latencies, 0.5),
        "insight_latency_p95_ms": _percentile(latencies, 0.95),
    }
    if totals["unverified_claims"] or totals["faults_caught"] != totals["faults_injected"]:
        raise RuntimeError("evaluation safety gate failed")
    return {
        "mode": mode.value,
        "fault_rate": fault_rate,
        "scenarios": list(scenarios),
        "seeds": list(seeds),
        "summary": summary,
        "matches": matches,
    }


def write_report(report: dict[str, Any], json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = report["summary"]
    lines = [
        "# MatchLens evaluation",
        "",
        (
            f"Mode: `{report['mode']}` · Fault rate: `{report['fault_rate']}`"
            f" · Matches: {summary['matches']}"
        ),
        "",
        "| Measure | Result |",
        "| --- | ---: |",
        f"| Unverified numeric claims shipped | {summary['unverified_claims']} |",
        f"| Faults caught / injected | {summary['faults_caught']} / {summary['faults_injected']} |",
        f"| Fault catch rate | {_rate(summary['fault_catch_rate'])} |",
        f"| First-pass verification rate | {_rate(summary['first_pass_rate'])} |",
        f"| Fallback rate | {_rate(summary['fallback_rate'])} |",
        f"| Moments per match, mean | {summary['moments_per_match']} |",
        (
            "| Insight latency p50 / p95 (ms) | "
            f"{summary['insight_latency_p50_ms']} / {summary['insight_latency_p95_ms']} |"
        ),
        f"| LLM calls | {summary['llm_calls']} |",
        f"| Estimated input / output tokens | {summary['tokens_in']} / {summary['tokens_out']} |",
        "",
        "Insight latency measures Detector selection to completed verification in this offline "
        "harness. Cue delivery, profiles and cost estimation are planned for later milestones. "
        "Mock token counts are character-based estimates.",
        "",
        "| Scenario | Seed | Moments | First pass | Fallbacks | Claims | "
        "Faults caught / injected |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for match in report["matches"]:
        cells = [
            match["scenario"],
            match["seed"],
            match["moments"],
            match["first_pass"],
            match["fallbacks"],
            match["claims"],
            f"{match['faults_caught']} / {match['faults_injected']}",
        ]
        lines.append("| " + " | ".join(map(str, cells)) + " |")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
