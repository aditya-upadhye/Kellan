from __future__ import annotations

import asyncio

from matchlens.config import LLMMode, Settings
from matchlens.llm.client import create_llm_client
from matchlens.obs.telemetry import configure_console_tracing


async def main() -> None:
    settings = Settings()
    if settings.llm_mode is not LLMMode.FOUNDRY:
        raise SystemExit("Set LLM_MODE=foundry and the Foundry endpoint and model names")

    configure_console_tracing()
    response = await create_llm_client(settings).complete_json(
        "detector",
        "Return a JSON object with ok set to true.",
        "Confirm the Foundry connection.",
        {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        settings.fast_model or "",
        match_id="foundry-smoke",
    )
    if response != {"ok": True}:
        raise SystemExit(f"Unexpected Foundry response: {response}")
    print("Foundry call succeeded")


if __name__ == "__main__":
    asyncio.run(main())
