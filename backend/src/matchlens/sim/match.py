from dataclasses import dataclass
from random import Random

from matchlens.models.events import MatchEvent
from matchlens.models.match import MatchMetadata
from matchlens.sim.engine import MatchEngine
from matchlens.sim.tuning import DEFAULT_TUNING, EngineTuning
from matchlens.world.models import Club, League


@dataclass(frozen=True, slots=True)
class SimulatedMatch:
    metadata: MatchMetadata
    events: list[MatchEvent]


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


def simulate_match(
    metadata: MatchMetadata, tuning: EngineTuning = DEFAULT_TUNING
) -> SimulatedMatch:
    events = MatchEngine(metadata, Random(metadata.seed), tuning).run()
    return SimulatedMatch(metadata=metadata, events=events)
