from __future__ import annotations

import asyncio
import json
from collections import Counter
from typing import TYPE_CHECKING

from matchlens.agents.detector import DetectorAgent
from matchlens.agents.triggers import RuleTriggerEngine
from matchlens.config import LLMMode, Settings
from matchlens.llm.client import create_llm_client
from matchlens.metrics.engine import MetricsEngine
from matchlens.models.tracking import TrackingFrame
from matchlens.sim.match import simulate_scenario
from matchlens.sim.scenarios import load_scenario
from matchlens.world.meridian import MERIDIAN_LEAGUE

if TYPE_CHECKING:
    from matchlens.models.insights import Moment
    from matchlens.models.traces import AgentTrace


def mock_decisions(user: str) -> dict[str, object]:
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


async def check_match(scenario_name: str, seed: int) -> dict[str, int]:
    settings = Settings(llm_mode=LLMMode.OFF)
    scenario = load_scenario(scenario_name, settings.scenarios_dir)
    match = simulate_scenario(MERIDIAN_LEAGUE, scenario, seed, with_tracking=True)
    match_id = match.metadata.match_id
    metrics = MetricsEngine(match_id)
    triggers = RuleTriggerEngine(match_id)
    modes = (LLMMode.OFF, LLMMode.MOCK)
    traces: dict[LLMMode, list[AgentTrace]] = {mode: [] for mode in modes}
    detectors = {
        mode: DetectorAgent(
            create_llm_client(
                Settings(llm_mode=mode),
                {("detector", "batch"): mock_decisions} if mode is LLMMode.MOCK else None,
                traces[mode].append,
            ),
            "fast",
        )
        for mode in traces
    }
    moments: dict[LLMMode, list[Moment]] = {mode: [] for mode in modes}

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
        candidates = triggers.consume(item, snapshots)
        elapsed_ms = (item.clock.period - 1) * 45 * 60_000 + item.clock.ms
        for mode, detector in detectors.items():
            moments[mode].extend(await detector.evaluate(candidates, {}, elapsed_ms))

    counts = {mode.value: len(items) for mode, items in moments.items()}
    assert all(15 <= count <= 30 for count in counts.values()), (scenario_name, seed, counts)
    assert all(
        item.source == "agent"
        for item in moments[LLMMode.MOCK]
        if item.type not in {"goal", "card"}
    )
    assert not any(trace.status in {"error", "fallback"} for trace in traces[LLMMode.MOCK])
    assert Counter(
        item.type for item in moments[LLMMode.OFF] if item.type in {"goal", "card"}
    ) == Counter(item.type for item in moments[LLMMode.MOCK] if item.type in {"goal", "card"})
    return counts


async def main() -> None:
    for scenario_name in ("balanced", "late_comeback", "red_card_press"):
        for seed in (1, 2, 3):
            counts = await check_match(scenario_name, seed)
            print(
                f"{scenario_name} seed={seed}: off={counts['off']} mock={counts['mock']}",
                flush=True,
            )


if __name__ == "__main__":
    asyncio.run(main())
