import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from time import monotonic
from typing import Literal, cast

from pydantic import Field

from matchlens.agents.live import LiveAgentWorkflow
from matchlens.config import LLMMode, Settings
from matchlens.metrics.engine import MetricsEngine
from matchlens.models.base import Contract, TeamSide
from matchlens.models.cues import OverlayCue, Recap
from matchlens.models.envelope import StreamEnvelope
from matchlens.models.events import BaseEvent, GoalEvent, MatchEvent
from matchlens.models.match import MatchMetadata
from matchlens.models.metrics import MetricSnapshot
from matchlens.models.profiles import ViewerProfile
from matchlens.models.traces import AgentTrace
from matchlens.models.tracking import TrackingFrame
from matchlens.profiles import DEFAULT_PROFILES, get_profile
from matchlens.sim.match import SimulatedMatch, build_scenario_metadata, simulate_match
from matchlens.sim.scenarios import Injection, UnknownScenarioError, load_scenario
from matchlens.store.memory import MemoryMetricStore
from matchlens.world.meridian import MERIDIAN_LEAGUE

PlaybackSpeed = Literal[1, 10, 30, 60, "max"]
ControlAction = Literal["pause", "resume", "speed", "llm_mode"]


class StartMatchRequest(Contract):
    scenario: str = "balanced"
    seed: int = Field(default=42, ge=0)
    speed: PlaybackSpeed = 10
    profiles: list[str] = Field(
        default_factory=lambda: [profile.profile_id for profile in DEFAULT_PROFILES],
        min_length=1,
        max_length=len(DEFAULT_PROFILES),
    )


class MatchControlRequest(Contract):
    action: ControlAction
    value: PlaybackSpeed | LLMMode | None = None


@dataclass(slots=True)
class MatchSession:
    metadata: MatchMetadata
    speed: PlaybackSpeed
    profiles: tuple[ViewerProfile, ...] = DEFAULT_PROFILES
    llm_mode: LLMMode = LLMMode.MOCK
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
    workflow: LiveAgentWorkflow | None = None
    cues: list[OverlayCue] = field(default_factory=list[OverlayCue])
    recaps: dict[tuple[str, str], Recap] = field(default_factory=dict[tuple[str, str], Recap])
    traces: list[AgentTrace] = field(default_factory=list[AgentTrace])
    active_cues: dict[str, tuple[OverlayCue, int]] = field(
        default_factory=dict[str, tuple[OverlayCue, int]]
    )

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
        self.publish_nowait(message)

    def publish_nowait(self, message: StreamEnvelope) -> None:
        if message.kind in ("event", "frame", "trace", "recap"):
            self.history.append(message)
        if message.kind == "trace":
            self.traces.append(AgentTrace.model_validate(message.data))
        elif message.kind == "cue":
            if message.data.get("action") == "show":
                cue = OverlayCue.model_validate(
                    {key: value for key, value in message.data.items() if key != "action"}
                )
                self.cues.append(cue)
                self.active_cues[cue.cue_id] = (cue, int(monotonic() * 1000))
            elif message.data.get("action") == "remove":
                self.active_cues.pop(str(message.data["cue_id"]), None)
        elif message.kind == "recap":
            recap = Recap.model_validate(message.data)
            self.recaps[recap.profile_id, recap.kind] = recap
        for queue in tuple(self.subscribers):
            queue.put_nowait(message)

    def replay_cues(self) -> list[StreamEnvelope]:
        messages: list[StreamEnvelope] = []
        now_ms = int(monotonic() * 1000)
        for cue_id, (cue, sent_at) in tuple(self.active_cues.items()):
            elapsed = now_ms - sent_at
            remaining = cue.start_delay_ms + cue.duration_ms - elapsed
            if remaining <= 0:
                self.active_cues.pop(cue_id)
                continue
            restored = cue.model_copy(
                update={
                    "start_delay_ms": max(0, cue.start_delay_ms - elapsed),
                    "duration_ms": min(cue.duration_ms, remaining),
                }
            )
            messages.append(
                StreamEnvelope(
                    kind="cue",
                    match_id=self.metadata.match_id,
                    data={**restored.model_dump(mode="json"), "action": "show"},
                )
            )
        return messages


class MatchManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sessions: dict[str, MatchSession] = {}

    async def start(self, request: StartMatchRequest) -> MatchSession:
        if (
            sum(session.state not in {"complete", "error"} for session in self.sessions.values())
            >= self.settings.max_concurrent_matches
        ):
            raise ValueError("maximum concurrent matches reached")
        profiles = tuple(get_profile(profile_id) for profile_id in request.profiles)
        if any(profile is None for profile in profiles) or len(set(request.profiles)) != len(
            request.profiles
        ):
            raise ValueError("profiles must contain distinct known profile IDs")
        try:
            scenario = load_scenario(request.scenario, self.settings.scenarios_dir)
        except UnknownScenarioError as error:
            raise ValueError(str(error)) from error
        metadata = build_scenario_metadata(MERIDIAN_LEAGUE, scenario, request.seed)
        match_id = f"{metadata.match_id}-{uuid.uuid4().hex[:8]}"
        metadata = metadata.model_copy(update={"match_id": match_id})
        session = MatchSession(
            metadata=metadata,
            speed=request.speed,
            profiles=tuple(profile for profile in profiles if profile is not None),
            llm_mode=self.settings.llm_mode,
        )
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
            session.workflow = LiveAgentWorkflow(
                session.metadata,
                session.profiles,
                self.settings.model_copy(update={"llm_mode": session.llm_mode}),
                session.store,
                session.publish_nowait,
            )
            previous: tuple[int, int] | None = None
            for item in _ordered_inputs(match):
                await session.resume_gate.wait()
                stamp = (item.clock.period, item.clock.ms)
                if session.speed != "max" and previous is not None:
                    delta = (stamp[0] - previous[0]) * 45 * 60_000 + stamp[1] - previous[1]
                    if delta > 0:
                        await asyncio.sleep(delta / (1000 * session.speed))
                await session.resume_gate.wait()
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
                await session.workflow.consume(cast("MatchEvent | TrackingFrame", item), snapshots)
            await session.workflow.finish()
            session.state = "complete"
            await session.publish(_status(session))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            session.state = "error"
            session.error = str(error)
            await session.publish(_status(session))
        finally:
            if session.workflow is not None:
                await session.workflow.close()

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
            if request.value not in (1, 10, 30, 60, "max"):
                raise ValueError("speed control requires a playback speed")
            session.speed = cast("PlaybackSpeed", request.value)
        elif request.action == "llm_mode":
            if not isinstance(request.value, LLMMode):
                raise ValueError("llm_mode control requires mock, off or foundry")
            Settings.model_validate({**self.settings.model_dump(), "llm_mode": request.value})
            session.llm_mode = request.value
            if session.workflow is not None:
                session.workflow.client.set_mode(request.value)
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


async def session_stream(
    session: MatchSession, profiles: frozenset[str] | None = None
) -> AsyncIterator[StreamEnvelope]:
    queue: asyncio.Queue[StreamEnvelope] = asyncio.Queue()
    session.subscribers.add(queue)
    history = tuple(session.history)
    latest_metrics = tuple(session.latest_metrics.values())
    active_cues = session.replay_cues()
    try:
        yield _status(session)
        for message in history:
            if (
                message.kind != "recap"
                or profiles is None
                or message.data.get("profile_id") in profiles
            ):
                yield message
        for message in active_cues:
            if profiles is None or message.data.get("profile_id") in profiles:
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
            message = await queue.get()
            if (
                message.kind not in {"cue", "recap"}
                or profiles is None
                or message.data.get("profile_id") in profiles
            ):
                yield message
            if message.kind == "status" and message.data.get("state") in {"complete", "error"}:
                return
    finally:
        session.subscribers.discard(queue)
