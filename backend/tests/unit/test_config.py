from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

from matchlens.config import LLMMode, Settings, StoreMode, TransportMode

ENV_EXAMPLE_PATH = Path(__file__).resolve().parents[3] / ".env.example"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name.upper(), raising=False)


class EnvironmentOnlySettings(Settings):
    model_config = SettingsConfigDict(env_file=None)


class EnvExampleSettings(Settings):
    model_config = SettingsConfigDict(env_file=ENV_EXAMPLE_PATH)


def load_settings() -> Settings:
    return EnvironmentOnlySettings()


def test_defaults_run_fully_offline() -> None:
    settings = load_settings()

    assert settings.llm_mode is LLMMode.MOCK
    assert settings.transport is TransportMode.LOCAL
    assert settings.store is StoreMode.MEMORY
    assert settings.fault_inject_rate == 0.0
    assert settings.factcheck_qualitative is False


def test_reads_modes_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODE", "off")
    monkeypatch.setenv("FACTCHECK_QUALITATIVE", "on")
    monkeypatch.setenv("FAULT_INJECT_RATE", "0.5")

    settings = load_settings()

    assert settings.llm_mode is LLMMode.OFF
    assert settings.factcheck_qualitative is True
    assert settings.fault_inject_rate == 0.5


@pytest.mark.parametrize(
    ("mode_env", "mode_value", "missing_setting"),
    [
        ("LLM_MODE", "foundry", "FOUNDRY_PROJECT_ENDPOINT"),
        ("TRANSPORT", "eventhubs", "EVENTHUBS_FQDN"),
        ("STORE", "cosmos", "COSMOS_ENDPOINT"),
    ],
)
def test_cloud_modes_require_their_endpoints(
    monkeypatch: pytest.MonkeyPatch, mode_env: str, mode_value: str, missing_setting: str
) -> None:
    monkeypatch.setenv(mode_env, mode_value)

    with pytest.raises(ValidationError, match=missing_setting):
        load_settings()


def test_foundry_mode_accepts_complete_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODE", "foundry")
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example.services.ai.azure.com")
    monkeypatch.setenv("FAST_MODEL", "fast")
    monkeypatch.setenv("STRONG_MODEL", "strong")

    assert load_settings().llm_mode is LLMMode.FOUNDRY


@pytest.mark.parametrize("rate", ["-0.1", "1.5"])
def test_rejects_fault_rate_outside_unit_interval(
    monkeypatch: pytest.MonkeyPatch, rate: str
) -> None:
    monkeypatch.setenv("FAULT_INJECT_RATE", rate)

    with pytest.raises(ValidationError):
        load_settings()


def test_env_example_matches_offline_defaults() -> None:
    assert EnvExampleSettings().model_dump() == load_settings().model_dump()
