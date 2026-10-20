import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from fastapi.testclient import TestClient

from matchlens.agents.evidence import EvidenceAnchor
from matchlens.api.app import create_app
from matchlens.api.matches import MatchManager, MatchSession
from matchlens.metrics.engine import MetricsEngine
from matchlens.models.clock import MatchClock
from matchlens.models.cues import CheckerResult, CueProvenance, OverlayCue
from matchlens.models.events import KickoffEvent, PassAttrs, PassEvent
from matchlens.models.insights import Claim, Insight, Moment
from matchlens.models.pitch import Point
from matchlens.models.traces import AgentTrace
from matchlens.models.tracking import PlayerPos, TrackingFrame
from matchlens.profiles import DEFAULT_PROFILES
from matchlens.store.memory import MemoryMetricStore
from support.agent_workflow import metadata

if TYPE_CHECKING:
    from matchlens.agents.live import LiveAgentWorkflow


async def evidence_session() -> MatchSession:
    match = metadata()
    session = MatchSession(match, 10, DEFAULT_PROFILES[:3], state="running")
    kickoff = KickoffEvent(
        event_id=f"{match.match_id}-000001",
        match_id=match.match_id,
        seq=1,
        clock=MatchClock(period=1, ms=0),
        team_id="home",
        player_id="h09",
        location=Point(x=52.5, y=34),
    )
    action = PassEvent(
        event_id=f"{match.match_id}-000002",
        match_id=match.match_id,
        seq=2,
        clock=MatchClock(period=1, ms=1000),
        team_id="home",
        player_id="h09",
        location=Point(x=52.5, y=34),
        end_location=Point(x=60.5, y=34),
        outcome="complete",
        attrs=PassAttrs(
            receiver_id="h06", length_m=8, height="ground", under_pressure=False, ball_speed_kmh=36
        ),
    )
    frames = [
        TrackingFrame(
            match_id=match.match_id,
            frame_seq=index + 1,
            clock=MatchClock(period=1, ms=index * 1000),
            ball=Point(x=52.5 + index, y=34),
            ball_speed_kmh=3.6,
            players=[PlayerPos(player_id="h09", x=x, y=34, speed_kmh=3.6)],
        )
        for index, x in enumerate((52.5, 53.5, 57.5))
    ]
    engine = MetricsEngine(match.match_id)
    for item in (kickoff, frames[0], action, frames[1]):
        snapshots = (
            engine.consume_frame(item)
            if isinstance(item, TrackingFrame)
            else engine.consume_event(item)
        )
        for snapshot in snapshots:
            await session.store.put(match.match_id, snapshot)
    pinned = session.store.snapshot()
    # A later tracking update changes the same metric at the SAME event seq.
    for snapshot in engine.consume_frame(frames[2]):
        await session.store.put(match.match_id, snapshot)
    session.events = [kickoff, action]
    session.frames = frames
    moment = Moment(
        moment_id="distance-moment",
        match_id=match.match_id,
        type="player_spotlight",
        seq_start=2,
        seq_end=2,
        clock=frames[1].clock,
        rule_score=0.8,
        significance=0.8,
        evidence_metric_ids=["player.h09.distance_m"],
        subject_ids=["h09"],
        source="rule",
    )
    claim = Claim(
        claim_id="distance-claim",
        text_span="1 m",
        metric_id="player.h09.distance_m",
        value=1,
        as_of_seq=2,
    )
    insight = Insight(
        insight_id="distance-insight",
        moment_id=moment.moment_id,
        headline="A tracked run",
        body="The player covered 1 m.",
        claims=[claim],
        tags=["player_spotlight"],
        status="verified",
        attempts=2,
        errors=[],
    )
    session.workflow = cast(
        "LiveAgentWorkflow",
        SimpleNamespace(
            evidence={
                insight.insight_id: EvidenceAnchor(moment, insight, pinned),
                "unpublished": EvidenceAnchor(moment, insight, pinned),
            }
        ),
    )
    for profile in session.profiles:
        session.cues.append(
            OverlayCue(
                cue_id=f"cue-{profile.profile_id}",
                match_id=match.match_id,
                profile_id=profile.profile_id,
                insight_id=insight.insight_id,
                trigger_seq=2,
                clock=moment.clock,
                template="moment_card",
                slot="lower_third",
                priority=80,
                start_delay_ms=0,
                duration_ms=5000,
                expires_at=MatchClock(period=1, ms=61000),
                headline=insight.headline,
                body="El jugador recorrió 1 m." if profile.language == "es" else insight.body,
                language=profile.language,
                data={"claims": [claim.model_dump(mode="json")], "moment_id": moment.moment_id},
                provenance=CueProvenance(
                    metric_ids=[claim.metric_id],
                    checker=CheckerResult(passed=True, attempts=2, version="deterministic-v1"),
                    model_ids=["mock"],
                ),
            )
        )
    for moment_id in (moment.moment_id, "unrelated-moment"):
        session.traces.append(
            AgentTrace(
                trace_id=f"trace-{moment_id}",
                match_id=match.match_id,
                moment_id=moment_id,
                agent="fact_checker",
                action="verify",
                status="rejected",
                latency_ms=1,
                tokens_in=0,
                tokens_out=0,
                detail="value_mismatch",
                draft_text="The player covered 99 m.",
                ts=datetime.now(UTC),
            )
        )
    return session


@pytest.fixture
def client() -> Iterator[tuple[TestClient, MatchSession]]:
    session = asyncio.run(evidence_session())
    app = create_app()
    cast("MatchManager", app.state.match_manager).sessions[session.metadata.match_id] = session
    test_client = TestClient(app)
    try:
        yield test_client, session
    finally:
        test_client.close()


def test_pins_generation_time_values_and_independently_reproduces_them(
    client: tuple[TestClient, MatchSession],
) -> None:
    test_client, session = client
    live = asyncio.run(session.store.get(session.metadata.match_id, "player.h09.distance_m", 2))
    assert live is not None
    assert live.value == 5
    response = test_client.get(
        f"/api/matches/{session.metadata.match_id}/insights/distance-insight/evidence"
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["versions"]) == 3
    for version in data["versions"]:
        claim = version["claims"][0]
        assert claim["snapshot"]["value"] == claim["recomputed_value"] == 1
        assert claim["recomputation"] == "matched"
        assert version["numeric_check_passed"]
    assert {frame["clock"]["ms"] for frame in data["replay"]["frames"]} == {0, 1000}
    assert all(event["seq"] <= 2 for event in data["replay"]["events"])
    assert len(data["traces"]) == 1
    assert data["traces"][0]["draft_text"] == "The player covered 99 m."
    assert "causation" in data["interpretation_note"]
    again = test_client.get(
        f"/api/matches/{session.metadata.match_id}/insights/distance-insight/evidence"
    )
    assert again.json()["evidence_id"] == data["evidence_id"]


def test_recomputation_exposes_a_bad_saved_value(client: tuple[TestClient, MatchSession]) -> None:
    test_client, session = client
    assert session.workflow is not None
    anchor = session.workflow.evidence["distance-insight"]
    original = asyncio.run(anchor.store.get(session.metadata.match_id, "player.h09.distance_m", 2))
    assert original is not None
    corrupt = MemoryMetricStore()
    asyncio.run(corrupt.put(session.metadata.match_id, original.model_copy(update={"value": 99})))
    session.workflow.evidence["distance-insight"] = EvidenceAnchor(
        anchor.moment, anchor.insight, corrupt.snapshot()
    )
    data = test_client.get(
        f"/api/matches/{session.metadata.match_id}/insights/distance-insight/evidence"
    ).json()
    check = data["versions"][0]["claims"][0]
    assert check["snapshot"]["value"] == 99
    assert check["recomputed_value"] == 1
    assert check["recomputation"] == "mismatch"
    assert not data["versions"][0]["numeric_check_passed"]


def test_does_not_expose_generated_but_unpublished_insights(
    client: tuple[TestClient, MatchSession],
) -> None:
    test_client, session = client
    response = test_client.get(
        f"/api/matches/{session.metadata.match_id}/insights/unpublished/evidence"
    )
    assert response.status_code == 404
    assert (
        test_client.get("/api/matches/missing/insights/distance-insight/evidence").status_code
        == 404
    )


def test_missing_raw_history_is_reported_as_unavailable(
    client: tuple[TestClient, MatchSession],
) -> None:
    test_client, session = client
    session.events = session.events[1:]
    response = test_client.get(
        f"/api/matches/{session.metadata.match_id}/insights/distance-insight/evidence"
    )
    assert response.status_code == 200
    check = response.json()["versions"][0]["claims"][0]
    assert check["recomputation"] == "unavailable"
    assert check["recomputed_value"] is None
