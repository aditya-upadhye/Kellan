import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, cast

from pydantic import Field

from matchlens.config import Settings
from matchlens.metrics.engine import MetricsEngine
from matchlens.models.base import Contract, TeamSide
from matchlens.models.envelope import StreamEnvelope
from matchlens.models.events import BaseEvent, GoalEvent, MatchEvent
from matchlens.models.match import MatchMetadata
from matchlens.models.metrics import MetricSnapshot
from matchlens.models.tracking import TrackingFrame
from matchlens.sim.match import SimulatedMatch, build_scenario_metadata, simulate_match
from matchlens.sim.scenarios import Injection, UnknownScenarioError, load_scenario
from matchlens.store.memory import MemoryMetricStore
from matchlens.world.meridian import MERIDIAN_LEAGUE

PlaybackSpeed = Literal[1, 10, 30, 60, "max"]
ControlAction = Literal["pause", "resume", "speed"]


class StartMatchRequest(Contract):
    scenario: str = "balanced"
    seed: int = Field(default=42, ge=0)
    speed: PlaybackSpeed = 10


class MatchControlRequest(Contract):
    action: ControlAction
    value: PlaybackSpeed | None = None


@dataclass(slots=True)
class MatchSession:
    metadata: MatchMetadata
    speed: PlaybackSpeed
    state: Literal["starting", "running", "paused", "complete", "error"] = "starting"
    clock: dict[str, int] = field(default_factory=lambda: {"period": 1, "ms": 0})
    events: list[BaseEvent] = field(default_factory=list[BaseEvent])
    frames: list[TrackingFrame] = field(default_factory=list[TrackingFrame])
    latest_metrics: dict[tuple[str, str], MetricSnapshot] = field(
        default_factory=dict[tuple[str, str], MetricSnapshot]
    )
    history: list[StreamEnvelope] = field(default_factory=list[StreamEnvelope])
    subscribers: set[asyncio.Queue[StreamEnvelope]] = field(
        default_factory=set[asyncio.Queue[StreamEnvelope]]
    )
    resume_gate: asyncio.Event = field(default_factory=asyncio.Event)
    store: MemoryMetricStore = field(default_factory=MemoryMetricStore)
    task: asyncio.Task[None] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        self.resume_gate.set()

    @property
    def score(self) -> dict[TeamSide, int]:
        goals: dict[TeamSide, int] = {"home": 0, "away": 0}
        for event in self.events:
            if isinstance(event, GoalEvent):
                goals[event.team_id] += 1
        return goals

    async def publish(self, message: StreamEnvelope) -> None:
        if message.kind in ("event", "frame"):
            self.history.append(message)
        for queue in tuple(self.subscribers):
            await queue.put(message)


class MatchManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sessions: dict[str, MatchSession] = {}

    async def start(self, request: StartMatchRequest) -> MatchSession:
        try:
            scenario = load_scenario(request.scenario, self.settings.scenarios_dir)
        except UnknownScenarioError as error:
            raise ValueError(str(error)) from error
        metadata = build_scenario_metadata(MERIDIAN_LEAGUE, scenario, request.seed)
        match_id = f"{metadata.match_id}-{uuid.uuid4().hex[:8]}"
        metadata = metadata.model_copy(update={"match_id": match_id})
        session = MatchSession(metadata=metadata, speed=request.speed)
        self.sessions[match_id] = session
        session.task = asyncio.create_task(self._run(session, scenario.injections))
        return session

    async def _run(self, session: MatchSession, injections: list[Injection]) -> None:
        try:
            match = await asyncio.to_thread(
                simulate_match,
                session.metadata,
                with_tracking=True,
                script=injections,
            )
            session.state = "running"
            await session.publish(_status(session))
            engine = MetricsEngine(session.metadata.match_id)
            previous: tuple[int, int] | None = None
            for item in _ordered_inputs(match):
                await session.resume_gate.wait()
                stamp = (item.clock.period, item.clock.ms)
                if session.speed != "max" and previous is not None:
                    delta = (stamp[0] - previous[0]) * 45 * 60_000 + stamp[1] - previous[1]
                    if delta > 0:
                        await asyncio.sleep(delta / (1000 * session.speed))
                previous = stamp
                session.clock = {"period": item.clock.period, "ms": item.clock.ms}
                if isinstance(item, TrackingFrame):
                    session.frames.append(item)
                    snapshots = engine.consume_frame(item)
                    message = StreamEnvelope(
                        kind="frame", match_id=item.match_id, data=item.model_dump(mode="json")
                    )
                else:
                    session.events.append(item)
                    snapshots = engine.consume_event(cast("MatchEvent", item))
                    message = StreamEnvelope(
                        kind="event", match_id=item.match_id, data=item.model_dump(mode="json")
                    )
                await session.publish(message)
                if snapshots:
                    await self._save_snapshots(session, snapshots)
            session.state = "complete"
            await session.publish(_status(session))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            session.state = "error"
            session.error = str(error)
            await session.publish(_status(session))

    async def _save_snapshots(self, session: MatchSession, snapshots: list[MetricSnapshot]) -> None:
        for snapshot in snapshots:
            await session.store.put(session.metadata.match_id, snapshot)
            session.latest_metrics[snapshot.metric_id, snapshot.window] = snapshot
        await session.publish(
            StreamEnvelope(
                kind="metrics",
                match_id=session.metadata.match_id,
                data={"snapshots": [item.model_dump(mode="json") for item in snapshots]},
            )
        )

    async def control(self, session: MatchSession, request: MatchControlRequest) -> None:
        if request.action == "pause":
            if session.state == "running":
                session.resume_gate.clear()
                session.state = "paused"
        elif request.action == "resume":
            if session.state == "paused":
                session.state = "running"
                session.resume_gate.set()
        elif request.action == "speed":
            if request.value is None:
                raise ValueError("speed control requires a value")
            session.speed = request.value
        await session.publish(_status(session))

    def get(self, match_id: str) -> MatchSession:
        try:
            return self.sessions[match_id]
        except KeyError as error:
            raise LookupError(f"match {match_id!r} was not found") from error

    async def close(self) -> None:
        tasks = [session.task for session in self.sessions.values() if session.task]
        for session in self.sessions.values():
            if session.task and not session.task.done():
                session.task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _ordered_inputs(match: SimulatedMatch) -> list[BaseEvent | TrackingFrame]:
    return sorted(
        [*match.events, *match.frames],
        key=lambda item: (
            item.clock.period,
            item.clock.ms,
            1 if isinstance(item, TrackingFrame) else 0,
        ),
    )


def _status(session: MatchSession) -> StreamEnvelope:
    return StreamEnvelope(
        kind="status",
        match_id=session.metadata.match_id,
        data={
            "state": session.state,
            "period": session.clock["period"],
            "clock_ms": session.clock["ms"],
            "speed": str(session.speed),
        },
    )


async def session_stream(session: MatchSession) -> AsyncIterator[StreamEnvelope]:
    queue: asyncio.Queue[StreamEnvelope] = asyncio.Queue()
    session.subscribers.add(queue)
    history = tuple(session.history)
    latest_metrics = tuple(session.latest_metrics.values())
    try:
        yield _status(session)
        for message in history:
            yield message
        if latest_metrics:
            yield StreamEnvelope(
                kind="metrics",
                match_id=session.metadata.match_id,
                data={"snapshots": [item.model_dump(mode="json") for item in latest_metrics]},
            )
        if session.state in ("complete", "error"):
            return
        while True:
            yield await queue.get()
    finally:
        session.subscribers.discard(queue)
