from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING

from matchlens.agents.detector import DETECTOR_INTERVAL_MS, DetectorAgent
from matchlens.agents.producer import ProducerScheduler, ScheduleResult
from matchlens.agents.timing import MatchTimeline
from matchlens.agents.triggers import CRITICAL_MOMENTS, RuleTriggerEngine
from matchlens.agents.workflow import (
    DetectionRequest,
    MomentResult,
    MomentWork,
    SelectedMoments,
    WorkflowServices,
    insight_workflow,
    selection_workflow,
)
from matchlens.llm.runtime import RuntimeLLMClient
from matchlens.models.clock import MatchClock
from matchlens.models.envelope import StreamEnvelope
from matchlens.models.events import GoalEvent
from matchlens.models.traces import AgentTrace
from matchlens.obs.telemetry import current_trace_id

if TYPE_CHECKING:
    from collections.abc import Callable

    from matchlens.config import Settings
    from matchlens.models.base import TeamSide
    from matchlens.models.events import MatchEvent
    from matchlens.models.insights import Insight, Moment
    from matchlens.models.match import MatchMetadata
    from matchlens.models.metrics import MetricSnapshot
    from matchlens.models.profiles import ViewerProfile
    from matchlens.models.traces import TraceStatus
    from matchlens.models.tracking import TrackingFrame
    from matchlens.store.memory import MemoryMetricStore


class LiveAgentWorkflow:
    def __init__(
        self,
        metadata: MatchMetadata,
        profiles: tuple[ViewerProfile, ...],
        settings: Settings,
        store: MemoryMetricStore,
        emit: Callable[[StreamEnvelope], None],
    ) -> None:
        self._emit = emit
        self._match_id = metadata.match_id
        self._store = store
        self.client = RuntimeLLMClient(settings, self._record_trace)
        self._services = WorkflowServices(
            self.client, settings, metadata, profiles, self._record_trace
        )
        self._detector = DetectorAgent(
            self.client, settings.fast_model or "mock-fast", self._record_trace
        )
        self._triggers = RuleTriggerEngine(metadata.match_id)
        self._scheduler = ProducerScheduler()
        self._timeline = MatchTimeline()
        self._clock = MatchClock(period=1, ms=0)
        self._score: dict[TeamSide, int] = {"home": 0, "away": 0}
        self.insights: list[Insight] = []
        self._contexts: dict[str, MomentWork] = {}
        self._candidates: dict[str, Moment] = {}
        self._last_review = 0
        self._last_admitted = 0
        self._seen: set[str] = set()
        self._wake_detector = asyncio.Event()
        self._semaphore = asyncio.Semaphore(4)
        self._delivery: asyncio.Queue[tuple[Moment, asyncio.Task[MomentResult | None]]] = (
            asyncio.Queue()
        )
        self._inflight: dict[str, tuple[Moment, asyncio.Task[MomentResult | None]]] = {}
        self._ending = False
        self._closed = False
        self._detector_task = asyncio.create_task(self._detect())
        self._delivery_task = asyncio.create_task(self._deliver())
        self._ticker_task = asyncio.create_task(self._tick())

    async def consume(
        self, item: MatchEvent | TrackingFrame, snapshots: list[MetricSnapshot]
    ) -> None:
        self._clock = item.clock
        elapsed = self._timeline.advance(item.clock)
        if isinstance(item, GoalEvent):
            self._score[item.team_id] += 1
        candidates = self._triggers.consume(item, snapshots)
        for moment in candidates:
            self._contexts[moment.moment_id] = MomentWork(
                moment, self._store.snapshot(), self._score.copy()
            )
            if moment.type not in CRITICAL_MOMENTS:
                self._candidates[moment.moment_id] = moment
        critical = [moment for moment in candidates if moment.type in CRITICAL_MOMENTS]
        if critical:
            await self._select(DetectionRequest(critical, elapsed, critical=True))
        if elapsed - self._last_review >= DETECTOR_INTERVAL_MS:
            self._last_review = elapsed
            self._wake_detector.set()
        self._schedule(self._scheduler.advance(self._clock, self._wall_ms()))
        self._discard_stale_contexts()
        await asyncio.sleep(0)

    async def _detect(self) -> None:
        while True:
            await self._wake_detector.wait()
            self._wake_detector.clear()
            candidates = list(self._candidates.values())
            self._candidates.clear()
            await self._select(
                DetectionRequest(
                    candidates,
                    self._timeline.elapsed(self._clock),
                    flush=self._ending,
                )
            )
            if self._ending and not self._candidates:
                return

    async def _select(self, request: DetectionRequest) -> None:
        result = await selection_workflow(self._detector).run(request)
        for output in result.get_outputs():
            if not isinstance(output, SelectedMoments):
                raise TypeError("unexpected Detector workflow output")
            for moment in sorted(output.moments, key=lambda item: (item.seq_end, item.moment_id)):
                self._admit(moment)

    def _admit(self, moment: Moment) -> None:
        if moment.moment_id in self._seen:
            return
        self._seen.add(moment.moment_id)
        if self._stale(moment) or moment.seq_end < self._last_admitted:
            self._trace(moment.moment_id, "drop", "rejected", "stale or out-of-order selection")
            return
        context = next(
            (
                work
                for work in self._contexts.values()
                if work.moment.seq_end == moment.seq_end and work.moment.clock == moment.clock
            ),
            None,
        )
        if context is None or len(self._inflight) >= 64:
            self._trace(
                moment.moment_id, "drop", "rejected", "context unavailable or workflow backlog full"
            )
            return
        work = replace(context, moment=moment, recent=tuple(self.insights[-3:]))
        self._last_admitted = moment.seq_end
        task = asyncio.create_task(self._generate(work))
        self._inflight[moment.moment_id] = (moment, task)
        self._delivery.put_nowait((moment, task))

    async def _generate(self, work: MomentWork) -> MomentResult | None:
        async with self._semaphore:
            if self._stale(work.moment):
                return None
            try:
                async with asyncio.timeout(12):
                    result = await insight_workflow(self._services).run(work)
                outputs = result.get_outputs()
                if len(outputs) != 1 or not isinstance(outputs[0], MomentResult):
                    raise TypeError("unexpected insight workflow output")
                return outputs[0]
            except Exception as error:
                self._trace(work.moment.moment_id, "workflow", "error", type(error).__name__)
                return None

    async def _deliver(self) -> None:
        while True:
            moment, task = await self._delivery.get()
            try:
                result = await task
                if result is not None:
                    self.insights.append(result.insight)
                    for cue in result.cues:
                        self._schedule(
                            self._scheduler.offer(cue, moment.type, self._clock, self._wall_ms())
                        )
            except asyncio.CancelledError:
                if self._closed:
                    raise
                self._trace(moment.moment_id, "drop", "rejected", "cue expired during generation")
            finally:
                self._inflight.pop(moment.moment_id, None)
                self._delivery.task_done()

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(0.1)
            self._schedule(self._scheduler.advance(self._clock, self._wall_ms()))
            for moment, task in tuple(self._inflight.values()):
                if self._stale(moment) and not task.done():
                    task.cancel()

    def _schedule(self, result: ScheduleResult) -> None:
        for cue in result.preempted:
            self._emit(
                StreamEnvelope(
                    kind="cue",
                    match_id=self._match_id,
                    data={
                        "action": "remove",
                        "cue_id": cue.cue_id,
                        "profile_id": cue.profile_id,
                        "reason": "preempted",
                    },
                )
            )
            self._trace(str(cue.data["moment_id"]), "preempt", "ok", cue.cue_id)
        for cue in result.expired:
            self._trace(str(cue.data["moment_id"]), "expire", "rejected", cue.cue_id)
        for cue in result.delivered:
            self._emit(
                StreamEnvelope(
                    kind="cue",
                    match_id=self._match_id,
                    data={
                        **cue.model_dump(mode="json"),
                        "action": "show",
                    },
                )
            )
            self._trace(str(cue.data["moment_id"]), "deliver", "ok", cue.cue_id)

    def _stale(self, moment: Moment) -> bool:
        return self._timeline.elapsed(self._clock) - self._timeline.elapsed(moment.clock) >= 60_000

    def _discard_stale_contexts(self) -> None:
        self._contexts = {
            key: work for key, work in self._contexts.items() if not self._stale(work.moment)
        }

    def _record_trace(self, trace: AgentTrace) -> None:
        self._emit(
            StreamEnvelope(
                kind="trace", match_id=self._match_id, data=trace.model_dump(mode="json")
            )
        )

    def _trace(self, moment_id: str, action: str, status: TraceStatus, detail: str) -> None:
        self._record_trace(
            AgentTrace(
                trace_id=current_trace_id(),
                match_id=self._match_id,
                moment_id=moment_id,
                agent="producer",
                action=action,
                status=status,
                latency_ms=0,
                tokens_in=0,
                tokens_out=0,
                detail=detail[:200],
                ts=datetime.now(UTC),
            )
        )

    @staticmethod
    def _wall_ms() -> int:
        return int(monotonic() * 1000)

    async def finish(self) -> None:
        self._ending = True
        self._wake_detector.set()
        await self._detector_task
        await self._delivery.join()
        await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        tasks = [
            self._detector_task,
            self._delivery_task,
            self._ticker_task,
            *(task for _, task in self._inflight.values()),
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
