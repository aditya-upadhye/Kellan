from typing import Any

from matchlens.models.clock import MatchClock
from matchlens.models.events import MatchEvent, format_event_id
from matchlens.sim.space import Period


class EventLog:
    def __init__(self, match_id: str) -> None:
        self._match_id = match_id
        self._events: list[MatchEvent] = []
        self.period: Period = 1
        self.ms = 0

    @property
    def events(self) -> list[MatchEvent]:
        return list(self._events)

    @property
    def clock(self) -> MatchClock:
        return MatchClock(period=self.period, ms=self.ms)

    def start_period(self, period: Period) -> None:
        self.period = period
        self.ms = 0

    def advance(self, duration_ms: int) -> None:
        self.ms += duration_ms

    def emit[EventT: MatchEvent](self, event_type: type[EventT], **fields: Any) -> EventT:
        seq = len(self._events) + 1
        event = event_type(
            event_id=format_event_id(self._match_id, seq),
            match_id=self._match_id,
            seq=seq,
            clock=self.clock,
            **fields,
        )
        self._events.append(event)
        return event
