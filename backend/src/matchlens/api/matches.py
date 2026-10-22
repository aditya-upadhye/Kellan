import asyncio
import uuid
from collections import OrderedDict, deque
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass, field
from time import monotonic
from typing import Literal, cast

from pydantic import Field, StrictBool

from matchlens.agents.live import LiveAgentWorkflow
from matchlens.config import LLMMode, Settings
from matchlens.metrics.engine import MetricsEngine
from matchlens.models.base import Contract, TeamSide
from matchlens.models.clock import MatchClock
from matchlens.models.cues import OverlayCue, Recap
from matchlens.models.envelope import StreamEnvelope
from matchlens.models.events import BaseEvent, GoalEvent, MatchEvent
from matchlens.models.match import MatchMetadata
from matchlens.models.metrics import MetricSnapshot
from matchlens.models.profiles import ViewerProfile
from matchlens.models.traces import AgentTrace
from matchlens.models.tracking import TrackingFrame
from matchlens.profiles import DEFAULT_PROFILES, get_profile
from matchlens.sim.match import build_scenario_metadata
from matchlens.sim.scenarios import Injection, UnknownScenarioError, load_scenario
from matchlens.sim.stream import stream_match
from matchlens.store.memory import MemoryMetricStore
from matchlens.world.meridian import MERIDIAN_LEAGUE

PlaybackSpeed = Literal[1, 10, 30, 60, "max"]
ControlAction = Literal["pause", "resume", "speed", "llm_mode", "inject_fault"]
TERMINAL_STATES = frozenset({"complete", "error", "stopped"})
START_WINDOW_SECONDS = 60 * 60
MAX_TRACKED_CLIENT_IPS = 10_000


class MatchStartRateLimitError(ValueError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("maximum match starts per IP per hour reached")
        self.retry_after_seconds = retry_after_seconds


class MatchCapacityError(ValueError):
    pass


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
    enabled: StrictBool | None = None


@dataclass(slots=True)
class MatchSession:
    metadata: MatchMetadata
    speed: PlaybackSpeed
    profiles: tuple[ViewerProfile, ...] = DEFAULT_PROFILES
    llm_mode: LLMMode = LLMMode.MOCK
    fault_inject_requested: bool = False
    insight_waiting: bool = False
    state: Literal["starting", "running", "paused", "complete", "error", "stopped"] = "starting"
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
    viewer_changed: asyncio.Event = field(default_factory=asyncio.Event)
    started_at: float = field(default_factory=monotonic)
    store: MemoryMetricStore = field(default_factory=MemoryMetricStore)
    task: asyncio.Task[None] | None = None
    idle_task: asyncio.Task[None] | None = None
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

    @property
    def fault_inject_next(self) -> bool:
        if self.workflow is not None:
            return self.workflow.fault_injection_armed
        return self.fault_inject_requested

    @property
    def effective_llm_mode(self) -> LLMMode:
        return self.workflow.client.mode if self.workflow is not None else self.llm_mode

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
        self._match_starts_by_ip: OrderedDict[str, deque[float]] = OrderedDict()

    async def start(self, request: StartMatchRequest, client_ip: str = "unknown") -> MatchSession:
        if self.settings.judge_mode:
            request = StartMatchRequest(
                scenario="late_comeback",
                seed=1,
                speed=10,
                profiles=[profile.profile_id for profile in DEFAULT_PROFILES],
            )
        profiles = tuple(get_profile(profile_id) for profile_id in request.profiles)
        if any(profile is None for profile in profiles) or len(set(request.profiles)) != len(
            request.profiles
        ):
            raise ValueError("profiles must contain distinct known profile IDs")
        try:
            scenario = load_scenario(request.scenario, self.settings.scenarios_dir)
        except UnknownScenarioError as error:
            raise ValueError(str(error)) from error
        if (
            sum(session.state not in TERMINAL_STATES for session in self.sessions.values())
            >= self.settings.max_concurrent_matches
        ):
            raise MatchCapacityError("maximum concurrent matches reached")
        self._record_match_start(client_ip)
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
        session.idle_task = asyncio.create_task(self._stop_when_unwatched(session))
        session.task = asyncio.create_task(self._run(session, scenario.injections))
        return session

    def _record_match_start(self, client_ip: str) -> None:
        now = monotonic()
        starts: deque[float] | None = self._match_starts_by_ip.get(client_ip)
        if starts is None:
            if len(self._match_starts_by_ip) >= MAX_TRACKED_CLIENT_IPS:
                self._match_starts_by_ip.popitem(last=False)
            starts = deque[float]()
            self._match_starts_by_ip[client_ip] = starts
        cutoff = now - START_WINDOW_SECONDS
        while starts and starts[0] <= cutoff:
            starts.popleft()
        if len(starts) >= self.settings.max_match_starts_per_ip_per_hour:
            retry_after = max(1, int(starts[0] + START_WINDOW_SECONDS - now + 0.999))
            raise MatchStartRateLimitError(retry_after)
        starts.append(now)
        self._match_starts_by_ip.move_to_end(client_ip)

    async def _stop_when_unwatched(self, session: MatchSession) -> None:
        idle_since = session.started_at
        try:
            while session.state not in TERMINAL_STATES:
                session.viewer_changed.clear()
                if session.subscribers:
                    await session.viewer_changed.wait()
                    idle_since = monotonic()
                    continue
                remaining = self.settings.match_idle_timeout_seconds - (monotonic() - idle_since)
                if remaining <= 0:
                    if session.subscribers or session.viewer_changed.is_set():
                        idle_since = monotonic()
                        continue
                    session.state = "stopped"
                    session.error = "Match stopped after no viewers were connected"
                    await session.publish(_status(session))
                    if session.task is not None and not session.task.done():
                        session.task.cancel()
                    return
                if session.subscribers:
                    continue
                changed = False
                try:
                    await asyncio.wait_for(session.viewer_changed.wait(), timeout=remaining)
                except TimeoutError:
                    changed = False
                else:
                    changed = True
                if changed:
                    idle_since = monotonic()
        except asyncio.CancelledError:
            raise

    async def _run(self, session: MatchSession, injections: list[Injection]) -> None:
        try:
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
            if session.fault_inject_requested:
                session.workflow.set_fault_injection(True)
                session.fault_inject_requested = False
            previous: tuple[int, int] | None = None
            async with aclosing(stream_match(session.metadata, script=injections)) as inputs:
                async for item in inputs:
                    await session.resume_gate.wait()
                    stamp = (item.clock.period, item.clock.ms)
                    if session.speed != "max" and previous is not None:
                        delta = (stamp[0] - previous[0]) * 45 * 60_000 + stamp[1] - previous[1]
                        if delta > 0:
                            await asyncio.sleep(delta / (1000 * session.speed))
                    await session.resume_gate.wait()
                    await self._wait_for_insights(session, item.clock)
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
                    await session.workflow.consume(
                        cast("MatchEvent | TrackingFrame", item), snapshots
                    )
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
            session.viewer_changed.set()

    async def _wait_for_insights(self, session: MatchSession, clock: MatchClock) -> None:
        workflow = session.workflow
        if workflow is None or not workflow.playback_blocked_at(clock):
            return
        session.insight_waiting = True
        await session.publish(_status(session))
        try:
            await workflow.wait_for_playback(clock)
        finally:
            session.insight_waiting = False
            await session.publish(_status(session))
        await session.resume_gate.wait()

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
        elif request.action == "inject_fault":
            _set_fault_injection(session, request.enabled)
        await session.publish(_status(session))

    def get(self, match_id: str) -> MatchSession:
        try:
            return self.sessions[match_id]
        except KeyError as error:
            raise LookupError(f"match {match_id!r} was not found") from error

    async def close(self) -> None:
        tasks = [
            task
            for session in self.sessions.values()
            for task in (session.task, session.idle_task)
            if task is not None
        ]
        for session in self.sessions.values():
            for task in (session.task, session.idle_task):
                if task is not None and not task.done():
                    task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _set_fault_injection(session: MatchSession, value: object) -> None:
    if type(value) is not bool:
        raise ValueError("fault injection control requires a boolean value")
    if session.workflow is not None:
        session.workflow.set_fault_injection(value)
    else:
        session.fault_inject_requested = value


def _status(session: MatchSession) -> StreamEnvelope:
    return StreamEnvelope(
        kind="status",
        match_id=session.metadata.match_id,
        data={
            "state": session.state,
            "period": session.clock["period"],
            "clock_ms": session.clock["ms"],
            "speed": str(session.speed),
            "insight_waiting": session.insight_waiting,
        },
    )


async def session_stream(
    session: MatchSession, profiles: frozenset[str] | None = None
) -> AsyncIterator[StreamEnvelope]:
    queue: asyncio.Queue[StreamEnvelope] = asyncio.Queue()
    session.subscribers.add(queue)
    session.viewer_changed.set()
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
        if session.state in TERMINAL_STATES:
            return
        while True:
            message = await queue.get()
            if (
                message.kind not in {"cue", "recap"}
                or profiles is None
                or message.data.get("profile_id") in profiles
            ):
                yield message
            if message.kind == "status" and message.data.get("state") in TERMINAL_STATES:
                return
    finally:
        session.subscribers.discard(queue)
        session.viewer_changed.set()
