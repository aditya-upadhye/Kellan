from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from matchlens.agents.detector import DetectorAgent
from matchlens.llm.client import MockLLMClient, OffLLMClient
from matchlens.models.clock import MatchClock
from matchlens.models.insights import Moment, MomentType

if TYPE_CHECKING:
    from matchlens.models.traces import AgentTrace

MATCH_ID = "detector-test"


def candidate(seq: int, *, kind: MomentType = "milestone", subject: str = "h09") -> Moment:
    score = 0.3 if kind == "milestone" else 0.6
    return Moment(
        moment_id=f"{MATCH_ID}-{seq}-{kind}-{subject}",
        match_id=MATCH_ID,
        type=kind,
        seq_start=seq,
        seq_end=seq,
        clock=MatchClock(period=1, ms=seq * 1000),
        rule_score=score,
        significance=score,
        evidence_metric_ids=["player.h09.passes"],
        subject_ids=[subject],
        source="rule",
    )


def mock_client(response: dict[str, Any]) -> MockLLMClient:
    return MockLLMClient({("detector", "batch"): response})


def test_detector_waits_for_tick_then_applies_decisions_and_compatible_merge() -> None:
    first = candidate(1)
    second = candidate(2)
    third = candidate(3, subject="a09")
    response = {
        "decisions": [
            {"moment_id": item.moment_id, "keep": item is not third, "significance": 0.8}
            for item in (first, second, third)
        ],
        "merge_groups": [[first.moment_id, second.moment_id]],
    }
    detector = DetectorAgent(mock_client(response), "fast")

    assert asyncio.run(detector.evaluate([first, second, third], {}, 14_999)) == []
    result = asyncio.run(detector.evaluate([], {}, 15_000))

    assert len(result) == 1
    assert result[0].source == "agent"
    assert result[0].significance == 0.8
    assert result[0].seq_start == 1
    assert result[0].seq_end == 2


def test_detector_fallback_uses_rule_score_and_emits_off_trace() -> None:
    traces: list[AgentTrace] = []
    detector = DetectorAgent(OffLLMClient(traces.append), "fast")
    item = candidate(1)

    result = asyncio.run(detector.evaluate([item], {}, 15_000))

    assert result[0].source == "fallback"
    assert result[0].significance == item.rule_score
    assert traces[0].agent == "detector"
    assert traces[0].status == "fallback"


def test_critical_moments_pass_immediately_and_are_not_rate_limited() -> None:
    client = mock_client({"decisions": [], "merge_groups": []})
    detector = DetectorAgent(client, "fast")
    goal = candidate(1, kind="goal")
    card = candidate(2, kind="card")

    first = asyncio.run(detector.evaluate([goal], {}, 1))
    second = asyncio.run(detector.evaluate([card], {}, 2))

    assert first == [goal]
    assert second == [card]


def test_one_noncritical_candidate_per_two_minutes() -> None:
    response: dict[str, Any] = {"decisions": [], "merge_groups": []}
    detector = DetectorAgent(mock_client(response), "fast")
    first = candidate(1)
    second = candidate(2, kind="big_chance")
    response["decisions"] = [{"moment_id": first.moment_id, "keep": True, "significance": 0.4}]
    assert len(asyncio.run(detector.evaluate([first], {}, 15_000))) == 1

    response["decisions"] = [{"moment_id": second.moment_id, "keep": True, "significance": 0.9}]
    assert asyncio.run(detector.evaluate([second], {}, 30_000)) == []
    assert len(asyncio.run(detector.evaluate([], {}, 135_000))) == 1


def test_invalid_response_falls_back_for_entire_batch() -> None:
    detector = DetectorAgent(mock_client({"decisions": [], "merge_groups": []}), "fast")
    item = candidate(1)

    result = asyncio.run(detector.evaluate([item], {}, 15_000))

    assert len(result) == 1
    assert result[0].source == "fallback"
    assert result[0].significance == item.rule_score


def test_incompatible_merge_proposal_falls_back() -> None:
    first = candidate(1)
    second = candidate(2, subject="a09")
    response = {
        "decisions": [
            {"moment_id": first.moment_id, "keep": True, "significance": 0.8},
            {"moment_id": second.moment_id, "keep": True, "significance": 0.7},
        ],
        "merge_groups": [[first.moment_id, second.moment_id]],
    }
    detector = DetectorAgent(mock_client(response), "fast")

    result = asyncio.run(detector.evaluate([first, second], {}, 15_000))

    assert len(result) == 1
    assert result[0].source == "fallback"
    assert result[0].significance == result[0].rule_score
