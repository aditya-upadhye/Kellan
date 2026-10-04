from typing import Literal

from pydantic import Field

from matchlens.models.base import Contract

MS_PER_MINUTE = 60_000
REGULATION_PERIOD_MINUTES = 45


class MatchClock(Contract):
    period: Literal[1, 2]
    ms: int = Field(ge=0)

    @property
    def display(self) -> str:
        minutes_before_period = (self.period - 1) * REGULATION_PERIOD_MINUTES
        regulation_end = minutes_before_period + REGULATION_PERIOD_MINUTES
        minute = minutes_before_period + self.ms // MS_PER_MINUTE + 1
        if minute <= regulation_end:
            return f"{minute}'"
        return f"{regulation_end}+{minute - regulation_end}'"
