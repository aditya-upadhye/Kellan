from __future__ import annotations

import asyncio

from matchlens.agents.evidence import moment_evidence
from matchlens.models.clock import MatchClock
from matchlens.models.insights import Moment
from matchlens.models.metrics import MetricSnapshot
from matchlens.store.memory import MemoryMetricStore

MATCH_ID = "evidence-match"


def reading(seq: int, value: float) -> MetricSnapshot:
    return MetricSnapshot(
        metric_id="match.momentum",
        scope="match",
        subject_id=None,
        label="Momentum",
        value=value,
        unit="index",
        window="match",
        as_of_seq=seq,
        clock=MatchClock(period=1, ms=seq * 1000),
    )


def moment(kind: str, seq_start: int, seq_end: int) -> Moment:
    return Moment.model_validate(
        {
            "moment_id": f"{MATCH_ID}-{seq_end}-{kind}-match",
            "match_id": MATCH_ID,
            "type": kind,
            "seq_start": seq_start,
            "seq_end": seq_end,
            "clock": MatchClock(period=1, ms=seq_end * 1000),
            "rule_score": 0.7,
            "significance": 0.7,
            "evidence_metric_ids": ["match.momentum"],
            "subject_ids": [],
            "source": "rule",
        }
    )


def evidence(selected: Moment, snapshots: list[MetricSnapshot]) -> list[tuple[int, float]]:
    async def run() -> list[MetricSnapshot]:
        store = MemoryMetricStore()
        for item in snapshots:
            await store.put(MATCH_ID, item)
        return await moment_evidence(selected, store)

    return [(item.as_of_seq, item.value) for item in asyncio.run(run())]


def test_momentum_swing_evidence_has_start_then_end_reading() -> None:
    readings = [reading(10, -72.0), reading(20, -50.0), reading(30, -39.2)]

    assert evidence(moment("momentum_swing", 10, 30), readings) == [(10, -72.0), (30, -39.2)]


def test_other_moment_types_keep_only_the_end_reading() -> None:
    readings = [reading(10, -72.0), reading(30, -39.2)]

    assert evidence(moment("goal", 10, 30), readings) == [(30, -39.2)]


def test_swing_without_a_start_reading_has_only_the_end_reading() -> None:
    assert evidence(moment("momentum_swing", 5, 30), [reading(30, -39.2)]) == [(30, -39.2)]


def test_swing_with_equal_bounds_does_not_duplicate_the_reading() -> None:
    assert evidence(moment("momentum_swing", 30, 30), [reading(30, -39.2)]) == [(30, -39.2)]


def test_readings_sharing_a_sequence_resolve_to_the_latest_of_that_sequence() -> None:
    readings = [reading(10, -72.0), reading(10, -70.0), reading(30, -39.2)]

    assert evidence(moment("momentum_swing", 10, 30), readings) == [(10, -70.0), (30, -39.2)]
