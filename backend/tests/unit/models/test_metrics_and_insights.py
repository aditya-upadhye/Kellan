from typing import Any

import pytest
from pydantic import ValidationError

from matchlens.models.insights import Moment
from matchlens.models.metrics import MetricSnapshot

CLOCK = {"period": 2, "ms": 600_000}


def snapshot_payload(metric_id: str, scope: str, subject_id: str | None) -> dict[str, Any]:
    return {
        "metric_id": metric_id,
        "scope": scope,
        "subject_id": subject_id,
        "label": "Expected goals",
        "value": 1.42,
        "unit": "xG",
        "window": "match",
        "as_of_seq": 812,
        "clock": CLOCK,
    }


@pytest.mark.parametrize(
    ("metric_id", "scope", "subject_id"),
    [
        ("team.home.xg", "team", "home"),
        ("player.h09.top_speed_kmh", "player", "h09"),
        ("event.m1-000812.xg", "event", "m1-000812"),
        ("match.momentum", "match", None),
    ],
)
def test_accepts_metric_ids_matching_scope_and_subject(
    metric_id: str, scope: str, subject_id: str | None
) -> None:
    snapshot = MetricSnapshot.model_validate(snapshot_payload(metric_id, scope, subject_id))

    assert snapshot.metric_id == metric_id


@pytest.mark.parametrize(
    ("metric_id", "scope", "subject_id", "reason"),
    [
        ("team.home.xg", "player", "home", "does not match scope"),
        ("team.home.xg", "team", "away", "expects subject_id home"),
        ("match.momentum", "match", "home", "expects subject_id None"),
        ("team..xg", "team", "home", "metric_id"),
        ("venue.capacity", "match", None, "metric_id"),
    ],
)
def test_rejects_inconsistent_metric_snapshots(
    metric_id: str, scope: str, subject_id: str | None, reason: str
) -> None:
    with pytest.raises(ValidationError, match=reason):
        MetricSnapshot.model_validate(snapshot_payload(metric_id, scope, subject_id))


def test_rejects_non_finite_metric_values() -> None:
    payload = snapshot_payload("match.momentum", "match", None) | {"value": float("nan")}

    with pytest.raises(ValidationError):
        MetricSnapshot.model_validate(payload)


def test_moment_rejects_reversed_sequence_range() -> None:
    payload = {
        "moment_id": "mo-1",
        "match_id": "m1",
        "type": "goal",
        "seq_start": 40,
        "seq_end": 39,
        "clock": CLOCK,
        "rule_score": 1.0,
        "significance": 1.0,
        "evidence_metric_ids": ["team.home.goals"],
        "subject_ids": ["home", "h09"],
        "source": "rule",
    }

    with pytest.raises(ValidationError, match="seq_end"):
        Moment.model_validate(payload)
