from matchlens.agents.workflow import MomentWork
from matchlens.config import LLMMode, Settings
from matchlens.models.clock import MatchClock
from matchlens.models.events import CardAttrs, CardEvent, format_event_id
from matchlens.models.insights import Moment
from matchlens.models.match import MatchMetadata
from matchlens.models.metrics import MetricSnapshot
from matchlens.sim.match import build_scenario_metadata
from matchlens.sim.scenarios import load_scenario
from matchlens.store.memory import MemoryMetricStore
from matchlens.world.meridian import MERIDIAN_LEAGUE


def settings(mode: LLMMode = LLMMode.MOCK) -> Settings:
    return Settings(llm_mode=mode, _env_file=None)


def metadata() -> MatchMetadata:
    return build_scenario_metadata(
        MERIDIAN_LEAGUE, load_scenario("balanced", settings().scenarios_dir), 1
    )


def card(seq: int, ms: int, match: MatchMetadata | None = None) -> CardEvent:
    match = match or metadata()
    return CardEvent(
        event_id=format_event_id(match.match_id, seq),
        match_id=match.match_id,
        seq=seq,
        clock=MatchClock(period=1, ms=ms),
        team_id="home",
        player_id="h09",
        outcome="yellow",
        attrs=CardAttrs(reason="foul"),
    )


def metric(value: float, seq: int = 1) -> MetricSnapshot:
    return MetricSnapshot(
        metric_id="team.home.goals",
        scope="team",
        subject_id="home",
        label="Goals",
        value=value,
        unit="count",
        window="match",
        as_of_seq=seq,
        clock=MatchClock(period=1, ms=1_000),
    )


async def goal_work() -> MomentWork:
    store = MemoryMetricStore()
    await store.put(metadata().match_id, metric(1))
    moment = Moment(
        moment_id="goal-home",
        match_id=metadata().match_id,
        type="goal",
        seq_start=1,
        seq_end=1,
        clock=MatchClock(period=1, ms=1_000),
        rule_score=1,
        significance=1,
        evidence_metric_ids=["team.home.goals"],
        subject_ids=["h09"],
        source="rule",
    )
    return MomentWork(moment, store.snapshot(), {"home": 1, "away": 0})
