from matchlens.models.clock import MS_PER_MINUTE, REGULATION_PERIOD_MINUTES, MatchClock


class MatchTimeline:
    def __init__(self) -> None:
        self._clock = MatchClock(period=1, ms=0)
        self._second_period_offset = REGULATION_PERIOD_MINUTES * MS_PER_MINUTE

    def advance(self, clock: MatchClock) -> int:
        if (clock.period, clock.ms) < (self._clock.period, self._clock.ms):
            raise ValueError("producer clock cannot move backwards")
        if clock.period > self._clock.period:
            self._second_period_offset = max(self._second_period_offset, self._clock.ms)
        self._clock = clock
        return self.elapsed(clock)

    def elapsed(self, clock: MatchClock) -> int:
        return clock.ms + (self._second_period_offset if clock.period == 2 else 0)
