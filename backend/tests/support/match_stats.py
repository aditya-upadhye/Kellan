from dataclasses import dataclass
from itertools import pairwise
from typing import Self

from matchlens.config import get_settings
from matchlens.models.base import TeamSide
from matchlens.models.events import (
    CardEvent,
    FoulEvent,
    GoalEvent,
    KickoffEvent,
    MatchEvent,
    PassEvent,
    PossessionChangeEvent,
    ShotEvent,
)
from matchlens.sim.match import simulate_scenario
from matchlens.sim.scenarios import load_scenario
from matchlens.world.meridian import MERIDIAN_LEAGUE


def balanced_summary(seed: int) -> "MatchSummary":
    """Independent seeded fixture, also callable in a test worker process."""
    scenario = load_scenario("balanced", get_settings().scenarios_dir)
    return MatchSummary.of(
        simulate_scenario(MERIDIAN_LEAGUE, scenario, seed, with_tracking=False).events
    )


def possession_shares(events: list[MatchEvent]) -> dict[TeamSide, float]:
    held_ms: dict[TeamSide, int] = {"home": 0, "away": 0}
    holder: TeamSide | None = None
    previous: MatchEvent | None = None
    for event in events:
        if (
            holder is not None
            and previous is not None
            and previous.clock.period == event.clock.period
        ):
            held_ms[holder] += event.clock.ms - previous.clock.ms
        if isinstance(event, KickoffEvent | PossessionChangeEvent):
            holder = event.team_id
        previous = event
    total_ms = held_ms["home"] + held_ms["away"]
    return {side: 100 * held / total_ms for side, held in held_ms.items()}


@dataclass(frozen=True, slots=True)
class MatchSummary:
    passes: int
    pass_accuracy_pct: float
    shots: int
    goals: int
    fouls: int
    yellow_cards: int
    home_possession_pct: float
    red_cards: int = 0
    longest_event_gap_ms: int = 0

    @classmethod
    def of(cls, events: list[MatchEvent]) -> Self:
        passes = [event for event in events if isinstance(event, PassEvent)]
        completed = sum(event.outcome == "complete" for event in passes)
        cautions = [
            event
            for event in events
            if isinstance(event, CardEvent) and event.outcome in ("yellow", "second_yellow")
        ]
        return cls(
            passes=len(passes),
            pass_accuracy_pct=100 * completed / len(passes),
            shots=sum(isinstance(event, ShotEvent) for event in events),
            goals=sum(isinstance(event, GoalEvent) for event in events),
            fouls=sum(isinstance(event, FoulEvent) for event in events),
            yellow_cards=len(cautions),
            home_possession_pct=possession_shares(events)["home"],
            red_cards=sum(
                isinstance(event, CardEvent) and event.outcome in ("red", "second_yellow")
                for event in events
            ),
            longest_event_gap_ms=max(
                (
                    later.clock.ms - earlier.clock.ms
                    for earlier, later in pairwise(events)
                    if earlier.clock.period == later.clock.period
                ),
                default=0,
            ),
        )
