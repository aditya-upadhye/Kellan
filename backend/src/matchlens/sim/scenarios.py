from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import Field, StringConstraints, field_validator, model_validator

from matchlens.models.base import Contract, Identifier, TeamSide
from matchlens.models.clock import MS_PER_MINUTE, REGULATION_PERIOD_MINUTES
from matchlens.models.match import StyleWeight, TeamStyle

SCENARIO_SUFFIX = ".yaml"
MS_PER_SECOND = 1_000
REGULATION_PERIOD_MS = REGULATION_PERIOD_MINUTES * MS_PER_MINUTE

ScenarioTime = Annotated[str, StringConstraints(pattern=r"^\d{1,2}:[0-5]\d$")]
StyleKey = Annotated[
    str, StringConstraints(pattern=r"^(home|away)\.(possession|press|directness)$")
]


class UnknownScenarioError(LookupError):
    pass


def scenario_time_ms(value: str) -> int:
    minutes, seconds = value.split(":")
    return (int(minutes) * 60 + int(seconds)) * MS_PER_SECOND


def _within_regulation(value: str) -> str:
    if scenario_time_ms(value) >= REGULATION_PERIOD_MS:
        raise ValueError(f"{value} must fall before {REGULATION_PERIOD_MINUTES}:00")
    return value


class ScriptedAction(Contract):
    period: Literal[1, 2]
    at: ScenarioTime
    action: Literal["red_card", "force_goal"]
    team: TeamSide

    @field_validator("at")
    @classmethod
    def at_falls_within_regulation(cls, value: str) -> str:
        return _within_regulation(value)

    @property
    def due_ms(self) -> int:
        return scenario_time_ms(self.at)


class StyleShift(Contract):
    period: Literal[1, 2]
    starts: ScenarioTime = Field(alias="from")
    modify: dict[StyleKey, float] = Field(min_length=1)

    @field_validator("starts")
    @classmethod
    def starts_within_regulation(cls, value: str) -> str:
        return _within_regulation(value)

    @property
    def due_ms(self) -> int:
        return scenario_time_ms(self.starts)

    def changes_for(self, side: TeamSide) -> dict[str, float]:
        prefix = f"{side}."
        return {
            key.removeprefix(prefix): delta
            for key, delta in self.modify.items()
            if key.startswith(prefix)
        }


Injection = ScriptedAction | StyleShift


class StyleOverride(Contract):
    possession: StyleWeight | None = None
    press: StyleWeight | None = None
    directness: StyleWeight | None = None

    def applied_to(self, style: TeamStyle) -> TeamStyle:
        return style.model_copy(update=self.model_dump(exclude_none=True))


class Scenario(Contract):
    name: Identifier
    description: str = Field(min_length=1, max_length=200)
    home: Identifier
    away: Identifier
    style_overrides: dict[TeamSide, StyleOverride] = Field(
        default_factory=dict[TeamSide, StyleOverride]
    )
    injections: list[Injection] = Field(default_factory=list[Injection])

    @model_validator(mode="after")
    def clubs_differ(self) -> Self:
        if self.home == self.away:
            raise ValueError("a club cannot play itself")
        return self

    def ordered_injections(self) -> list[Injection]:
        return sorted(self.injections, key=lambda injection: (injection.period, injection.due_ms))


def scenario_names(directory: Path) -> list[str]:
    return sorted(path.stem for path in directory.glob(f"*{SCENARIO_SUFFIX}"))


def load_scenario(name: str, directory: Path) -> Scenario:
    path = directory / f"{name}{SCENARIO_SUFFIX}"
    if not path.is_file():
        available = ", ".join(scenario_names(directory)) or "none"
        raise UnknownScenarioError(f"no scenario {name!r} (available: {available})")
    scenario = Scenario.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if scenario.name != name:
        raise ValueError(f"{path.name} declares name {scenario.name!r}")
    return scenario
