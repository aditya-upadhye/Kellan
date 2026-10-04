import json
from pathlib import Path
from typing import Any

from pydantic import JsonValue, TypeAdapter

from matchlens.models.cues import OverlayCue, Recap
from matchlens.models.envelope import StreamEnvelope
from matchlens.models.events import MATCH_EVENT_ADAPTER
from matchlens.models.insights import Insight, Moment
from matchlens.models.match import MatchMetadata
from matchlens.models.metrics import MetricSnapshot
from matchlens.models.profiles import ViewerProfile
from matchlens.models.traces import AgentTrace
from matchlens.models.tracking import TrackingFrame

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_FILE_SUFFIX = ".schema.json"

EXPORTED_CONTRACTS: dict[str, TypeAdapter[Any]] = {
    "MatchMetadata": TypeAdapter(MatchMetadata),
    "MatchEvent": MATCH_EVENT_ADAPTER,
    "TrackingFrame": TypeAdapter(TrackingFrame),
    "MetricSnapshot": TypeAdapter(MetricSnapshot),
    "Moment": TypeAdapter(Moment),
    "Insight": TypeAdapter(Insight),
    "ViewerProfile": TypeAdapter(ViewerProfile),
    "OverlayCue": TypeAdapter(OverlayCue),
    "Recap": TypeAdapter(Recap),
    "AgentTrace": TypeAdapter(AgentTrace),
    "StreamEnvelope": TypeAdapter(StreamEnvelope),
}


def schema_file_name(title: str) -> str:
    return f"{title}{SCHEMA_FILE_SUFFIX}"


def strip_field_annotations(schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    is_model = "properties" in schema
    stripped: dict[str, JsonValue] = {}
    for key, value in schema.items():
        if key == "default" or (key == "title" and not is_model):
            continue
        if key in ("properties", "$defs") and isinstance(value, dict):
            stripped[key] = {name: _strip_nested(child) for name, child in value.items()}
        else:
            stripped[key] = _strip_nested(value)
    return stripped


def _strip_nested(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return strip_field_annotations(value)
    if isinstance(value, list):
        return [_strip_nested(item) for item in value]
    return value


def render_json_schemas() -> dict[str, str]:
    rendered: dict[str, str] = {}
    for title, adapter in EXPORTED_CONTRACTS.items():
        schema = strip_field_annotations(adapter.json_schema(mode="serialization"))
        schema.pop("title", None)
        document = {"$schema": JSON_SCHEMA_DIALECT, "title": title, **schema}
        rendered[schema_file_name(title)] = json.dumps(document, indent=2) + "\n"
    return rendered


def export_json_schemas(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered = render_json_schemas()

    for stale_file in output_dir.glob(f"*{SCHEMA_FILE_SUFFIX}"):
        if stale_file.name not in rendered:
            stale_file.unlink()

    written: list[Path] = []
    for file_name, content in rendered.items():
        path = output_dir / file_name
        path.write_text(content, encoding="utf-8", newline="\n")
        written.append(path)
    return written
