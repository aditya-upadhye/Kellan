from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING, cast

from matchlens.agents.detector import DETECTOR_INTERVAL_MS, DetectorAgent
from matchlens.agents.evidence import EvidenceAnchor
from matchlens.agents.producer import ProducerScheduler, ScheduleResult
from matchlens.agents.recap import RecapAgent, RecapSource
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
from matchlens.config import LLMMode
from matchlens.llm.runtime import RuntimeLLMClient
from matchlens.models.clock import MatchClock
from matchlens.models.cues import Recap
from matchlens.models.envelope import StreamEnvelope
from matchlens.models.events import GoalEvent, PeriodEndEvent
from matchlens.models.insights import Claim, Insight, Moment
from matchlens.models.traces import AgentTrace
from matchlens.obs.telemetry import current_trace_id

if TYPE_CHECKING:
    from collections.abc import Callable

    from matchlens.config import Settings
    from matchlens.models.base import TeamSide
    from matchlens.models.cues import RecapKind
    from matchlens.models.events import MatchEvent
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
        self.evidence: dict[str, EvidenceAnchor] = {}
        self._contexts: dict[str, MomentWork] = {}
        self._candidates: dict[str, Moment] = {}
        self._selection_lock = asyncio.Lock()
        self._reviewing: tuple[Moment, ...] = ()
        self._playback_progress = asyncio.Event()
        self._delivery_condition = asyncio.Condition()
        self._profile_sources: dict[str, dict[str, RecapSource]] = {
            profile.profile_id: {} for profile in profiles
        }
        self._recap_tasks: set[asyncio.Task[None]] = set()
        self._fault_inject_next = False
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
        if isinstance(item, PeriodEndEvent):
            task = asyncio.create_task(
                self._generate_half_recaps(item.seq, elapsed, self._store.snapshot())
            )
            self._recap_tasks.add(task)
            task.add_done_callback(self._recap_tasks.discard)
        self._discard_stale_contexts()
        await asyncio.sleep(0)

    def set_fault_injection(self, enabled: bool) -> None:
        self._fault_inject_next = enabled

    @property
    def fault_injection_armed(self) -> bool:
        return self._fault_inject_next

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
        if request.critical:
            # Critical rule triggers must not queue behind a slow model review.
            result = await selection_workflow(self._detector).run(request)
        else:
            async with self._selection_lock:
                self._reviewing = tuple(request.candidates)
                try:
                    result = await selection_workflow(self._detector).run(request)
                finally:
                    self._reviewing = ()
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
        fault_inject_rate = 1.0 if self._fault_inject_next else None
        self._fault_inject_next = False
        if fault_inject_rate is not None:
            self._trace(moment.moment_id, "fault_injection", "ok", "armed for this moment")
        work = replace(
            context,
            moment=moment,
            recent=tuple(self.insights[-3:]),
            fault_inject_rate=fault_inject_rate,
        )
        self._last_admitted = moment.seq_end
        task = asyncio.create_task(self._generate(work))
        self._inflight[moment.moment_id] = (moment, task)
        self._delivery.put_nowait((moment, task))

    async def _generate(self, work: MomentWork) -> MomentResult | None:
        async with self._semaphore:
            if self._stale(work.moment):
                return None
            try:
                try:
                    async with asyncio.timeout(
                        self._services.settings.insight_generation_timeout_seconds
                    ):
                        result = await insight_workflow(self._services).run(work)
                except TimeoutError:
                    self._trace(
                        work.moment.moment_id,
                        "workflow",
                        "fallback",
                        "generation budget exhausted; using verified templates",
                    )
                    # A local fallback has its own client; do not switch other
                    # moments or future model calls off for the whole match.
                    fallback_client = RuntimeLLMClient(
                        self._services.settings.model_copy(update={"llm_mode": LLMMode.OFF}),
                        self._record_trace,
                    )
                    result = await insight_workflow(
                        replace(self._services, client=fallback_client)
                    ).run(replace(work, fault_inject_rate=0.0))
                outputs = result.get_outputs()
                if len(outputs) != 1 or not isinstance(outputs[0], MomentResult):
                    raise TypeError("unexpected insight workflow output")
                result = outputs[0]
                self.evidence[result.insight.insight_id] = EvidenceAnchor(
                    work.moment, result.insight, work.store
                )
                return result
            except Exception as error:
                self._trace(
                    work.moment.moment_id, "workflow", "error", f"{type(error).__name__}: {error}"
                )
                return None

    async def _deliver(self) -> None:
        while True:
            moment, task = await self._delivery.get()
            try:
                result = await task
                if result is not None:
                    self.insights.append(result.insight)
                    for cue in result.cues:
                        raw_claims = cue.data.get("claims", [])
                        claims = tuple(
                            Claim.model_validate(item)
                            for item in cast("list[dict[str, object]]", raw_claims)
                        )
                        self._profile_sources[cue.profile_id][moment.moment_id] = RecapSource(
                            moment=moment,
                            headline=cue.headline,
                            body=cue.body,
                            claims=claims,
                        )
                        self._schedule(
                            self._scheduler.offer(cue, moment.type, self._clock, self._wall_ms())
                        )
            except asyncio.CancelledError:
                if self._closed:
                    raise
                self._trace(moment.moment_id, "drop", "rejected", "cue expired during generation")
            finally:
                self._inflight.pop(moment.moment_id, None)
                async with self._delivery_condition:
                    self._delivery_condition.notify_all()
                self._delivery.task_done()

    async def _generate_half_recaps(
        self, through_seq: int, elapsed: int, cutoff: MemoryMetricStore
    ) -> None:
        try:
            candidates: list[Moment] = []
            for moment_id, moment in tuple(self._candidates.items()):
                if moment.seq_end <= through_seq:
                    candidates.append(self._candidates.pop(moment_id))
            await self._select(
                DetectionRequest(candidates, elapsed, flush=True, through_seq=through_seq)
            )
            async with asyncio.timeout(
                self._services.settings.insight_generation_timeout_seconds + 1
            ):
                async with self._delivery_condition:
                    await self._delivery_condition.wait_for(
                        lambda: (
                            not any(
                                moment.seq_end <= through_seq
                                for moment, _ in self._inflight.values()
                            )
                        )
                    )
        except TimeoutError:
            self._trace("recap", "wait", "fallback", "halftime insight delivery timed out")
        except Exception as error:
            self._trace("recap", "generate", "error", type(error).__name__)
            return
        await self._create_recaps("half", cutoff, through_seq)

    async def _create_recaps(
        self, kind: RecapKind, store: MemoryMetricStore, through_seq: int | None = None
    ) -> None:
        snapshots = await store.latest(self._match_id)
        if through_seq is not None:
            snapshots = [item for item in snapshots if item.as_of_seq <= through_seq]
        agent = RecapAgent(
            self.client,
            self._services.settings.strong_model or "mock-strong",
            self._match_id,
            self._record_trace,
            request_timeout_seconds=(
                self._services.settings.llm_request_timeout_seconds
                * self._services.settings.llm_request_attempts
                + 2
            ),
        )
        results = await asyncio.gather(
            *(
                agent.create_recap(
                    kind,
                    profile,
                    [
                        source
                        for source in self._profile_sources[profile.profile_id].values()
                        if through_seq is None or source.moment.seq_end <= through_seq
                    ],
                    snapshots,
                    store,
                )
                for profile in self._services.profiles
            ),
            return_exceptions=True,
        )
        for result in results:
            if not isinstance(result, Recap):
                self._trace("recap", "generate", "error", type(result).__name__)
                continue
            self._emit(
                StreamEnvelope(
                    kind="recap",
                    match_id=self._match_id,
                    data=result.model_dump(mode="json"),
                )
            )

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(0.1)
            self._schedule(self._scheduler.advance(self._clock, self._wall_ms()))
            for moment, task in tuple(self._inflight.values()):
                if self._stale(moment) and not task.done():
                    task.cancel()
            self._playback_progress.set()

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

    def playback_blocked_at(self, clock: MatchClock) -> bool:
        """Keep accelerated replay from outrunning in-progress story evidence.

        Leave 15 simulated seconds for scheduling before the existing one-minute
        freshness cutoff. The cutoff and immutable evidence remain unchanged.
        """
        if self._closed or self.client.mode is not LLMMode.FOUNDRY:
            return False
        next_elapsed = self._timeline.elapsed(clock)
        clocks = [
            *(moment.clock for moment in self._reviewing),
            *(moment.clock for moment, _ in self._inflight.values()),
            *self._scheduler.pending_clocks,
        ]
        return any(next_elapsed - self._timeline.elapsed(item) >= 45_000 for item in clocks)

    async def wait_for_playback(self, clock: MatchClock) -> None:
        # Model/workflow timeouts bound this wait. Scheduling continues on the
        # wall-clock ticker, and pause/stop controls stay responsive.
        while True:
            self._playback_progress.clear()
            if not self.playback_blocked_at(clock):
                return
            await self._playback_progress.wait()

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
        if self._recap_tasks:
            await asyncio.gather(*tuple(self._recap_tasks), return_exceptions=True)
        await self._delivery.join()
        await self._create_recaps("full", self._store.snapshot())
        self._fault_inject_next = False
        await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._playback_progress.set()
        tasks = [
            self._detector_task,
            self._delivery_task,
            self._ticker_task,
            *(task for _, task in self._inflight.values()),
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
