import json
from pathlib import Path

import pytest

from matchlens.cli import main
from matchlens.models.events import EventType
from matchlens.models.json_schema import (
    EXPORTED_CONTRACTS,
    export_json_schemas,
    render_json_schemas,
    schema_file_name,
)

COMMITTED_SCHEMAS_DIR = Path(__file__).resolve().parents[4] / "docs" / "schemas"


def test_committed_schemas_match_the_contracts() -> None:
    committed = {
        path.name: path.read_text(encoding="utf-8")
        for path in COMMITTED_SCHEMAS_DIR.glob("*.schema.json")
    }

    assert committed == render_json_schemas(), "schemas are stale: run `make schemas`"


def test_event_schema_discriminates_every_event_type() -> None:
    schema = json.loads(render_json_schemas()[schema_file_name("MatchEvent")])

    assert set(schema["discriminator"]["mapping"]) == {event_type.value for event_type in EventType}


def test_schemas_keep_model_titles_but_drop_field_titles_and_defaults() -> None:
    schema = json.loads(render_json_schemas()[schema_file_name("Recap")])

    assert schema["title"] == "Recap"
    assert "title" in schema["properties"]
    assert "title" not in schema["properties"]["recap_id"]
    assert "default" not in json.dumps(schema)


def test_export_writes_every_contract_and_removes_stale_files(tmp_path: Path) -> None:
    stale_file = tmp_path / "Removed.schema.json"
    stale_file.write_text("{}", encoding="utf-8")

    written = export_json_schemas(tmp_path)

    assert {path.name for path in written} == {schema_file_name(t) for t in EXPORTED_CONTRACTS}
    assert not stale_file.exists()
    assert all(b"\r\n" not in path.read_bytes() for path in written)


def test_cli_exports_schemas(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["schemas", "export", "--output-dir", str(tmp_path)])

    assert exit_code == 0
    assert f"wrote {len(EXPORTED_CONTRACTS)} schemas" in capsys.readouterr().out
