from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class LLMMode(StrEnum):
    MOCK = "mock"
    OFF = "off"
    FOUNDRY = "foundry"


class TransportMode(StrEnum):
    LOCAL = "local"
    EVENTHUBS = "eventhubs"


class StoreMode(StrEnum):
    MEMORY = "memory"
    COSMOS = "cosmos"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    llm_mode: LLMMode = LLMMode.MOCK
    transport: TransportMode = TransportMode.LOCAL
    store: StoreMode = StoreMode.MEMORY

    foundry_project_endpoint: str | None = None
    fast_model: str | None = None
    strong_model: str | None = None
    eventhubs_fqdn: str | None = None
    eventhubs_name: str = "matchlens"
    eventhubs_consumer_group: str = "$Default"
    cosmos_endpoint: str | None = None
    cosmos_database: str = "matchlens"
    cosmos_container: str = "metrics"
    applicationinsights_connection_string: str | None = None

    fault_inject_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    factcheck_qualitative: bool = False

    max_concurrent_matches: int = Field(default=2, ge=1)
    max_llm_calls_per_match: int = Field(default=400, ge=0)

    data_dir: Path = REPO_ROOT / "data"

    @property
    def scenarios_dir(self) -> Path:
        return self.data_dir / "scenarios"

    @property
    def samples_dir(self) -> Path:
        return self.data_dir / "samples"

    @model_validator(mode="after")
    def require_settings_for_cloud_modes(self) -> Self:
        required: dict[str, str | None] = {}
        if self.llm_mode is LLMMode.FOUNDRY:
            required["FOUNDRY_PROJECT_ENDPOINT"] = self.foundry_project_endpoint
            required["FAST_MODEL"] = self.fast_model
            required["STRONG_MODEL"] = self.strong_model
        if self.transport is TransportMode.EVENTHUBS:
            required["EVENTHUBS_FQDN"] = self.eventhubs_fqdn
        if self.store is StoreMode.COSMOS:
            required["COSMOS_ENDPOINT"] = self.cosmos_endpoint

        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"missing required settings: {', '.join(missing)}")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
