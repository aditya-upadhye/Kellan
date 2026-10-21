from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from random import Random

from matchlens.models.base import TeamSide
from matchlens.models.events import GoalEvent, MatchEvent
from matchlens.models.match import MatchMetadata, Team
from matchlens.models.tracking import TrackingFrame
from matchlens.sim.engine import MatchEngine
from matchlens.sim.scenarios import Injection, Scenario, StyleOverride
from matchlens.sim.tuning import DEFAULT_TUNING, EngineTuning
from matchlens.world.models import Club, League


@dataclass(frozen=True, slots=True)
class SimulatedMatch:
    metadata: MatchMetadata
    events: list[MatchEvent]
    frames: list[TrackingFrame]

    @property
    def score(self) -> dict[TeamSide, int]:
        goals = Counter(event.team_id for event in self.events if isinstance(event, GoalEvent))
        return {"home": goals["home"], "away": goals["away"]}


def match_id_for(scenario: str, seed: int) -> str:
    return f"{scenario}-s{seed}"


def build_match_metadata(
    league: League, home: Club, away: Club, *, scenario: str, seed: int
) -> MatchMetadata:
    return MatchMetadata(
        match_id=match_id_for(scenario, seed),
        competition=league.name,
        venue=home.venue,
        home=home.as_team("home"),
        away=away.as_team("away"),
        scenario=scenario,
        seed=seed,
    )


def build_scenario_metadata(league: League, scenario: Scenario, seed: int) -> MatchMetadata:
    metadata = build_match_metadata(
        league,
        league.club(scenario.home),
        league.club(scenario.away),
        scenario=scenario.name,
        seed=seed,
    )
    overrides = scenario.style_overrides
    return metadata.model_copy(
        update={
            "home": _restyled(metadata.home, overrides.get("home")),
            "away": _restyled(metadata.away, overrides.get("away")),
        }
    )


def _restyled(team: Team, override: StyleOverride | None) -> Team:
    if override is None:
        return team
    return team.model_copy(update={"style": override.applied_to(team.style)})


def simulate_match(
    metadata: MatchMetadata,
    tuning: EngineTuning = DEFAULT_TUNING,
    *,
    with_tracking: bool = True,
    script: Sequence[Injection] = (),
) -> SimulatedMatch:
    rng = Random(metadata.seed)
    engine = MatchEngine(metadata, rng, tuning, script, record_tracking=with_tracking)
    events = engine.run()
    frames = engine.world.frames if with_tracking else []
    return SimulatedMatch(metadata=metadata, events=events, frames=frames)


def simulate_scenario(
    league: League, scenario: Scenario, seed: int, *, with_tracking: bool = True
) -> SimulatedMatch:
    return simulate_match(
        build_scenario_metadata(league, scenario, seed),
        with_tracking=with_tracking,
        script=scenario.injections,
    )
