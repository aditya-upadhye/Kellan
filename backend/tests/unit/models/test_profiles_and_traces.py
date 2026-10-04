from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from matchlens.models.profiles import ViewerProfile
from matchlens.models.traces import AgentTrace

ANALYST_EN: dict[str, Any] = {
    "profile_id": "analyst_en",
    "label": "Analyst",
    "mode": "analyst",
    "language": "en",
    "favorite_team_id": None,
    "favorite_player_id": None,
    "focus_metric": None,
    "verbosity": "detailed",
}


def test_accepts_seed_profile() -> None:
    assert ViewerProfile.model_validate(ANALYST_EN).language == "en"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"mode": "player_focus"}, "favorite_player_id"),
        ({"language": "fr"}, "language"),
        ({"label": "x" * 41}, "label"),
        ({"focus_metric": "player.h09.top speed"}, "focus_metric"),
        ({"profile_id": "analyst en"}, "profile_id"),
    ],
)
def test_rejects_invalid_profiles(changes: dict[str, Any], reason: str) -> None:
    with pytest.raises(ValidationError, match=reason):
        ViewerProfile.model_validate(ANALYST_EN | changes)


def trace_payload(ts: datetime) -> dict[str, Any]:
    return {
        "trace_id": "tr-1",
        "match_id": "m1",
        "moment_id": "mo-1",
        "agent": "fact_checker",
        "action": "verify_claims",
        "status": "rejected",
        "latency_ms": 12,
        "tokens_in": 0,
        "tokens_out": 0,
        "detail": "value_mismatch on team.home.xg",
        "ts": ts,
    }


def test_trace_accepts_timezone_aware_timestamp() -> None:
    trace = AgentTrace.model_validate(trace_payload(datetime(2026, 10, 4, 12, 0, tzinfo=UTC)))

    assert trace.status == "rejected"


def test_trace_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        AgentTrace.model_validate(trace_payload(datetime(2026, 10, 4, 12, 0)))
