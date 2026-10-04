import argparse
from collections.abc import Sequence
from pathlib import Path

from matchlens import __version__
from matchlens.config import get_settings
from matchlens.models.json_schema import export_json_schemas

DEFAULT_SCHEMAS_DIR = Path("docs/schemas")


def run_info(_: argparse.Namespace) -> int:
    settings = get_settings()
    print(f"matchlens {__version__}")
    print(f"llm_mode={settings.llm_mode}")
    print(f"transport={settings.transport}")
    print(f"store={settings.store}")
    return 0


def run_schemas_export(args: argparse.Namespace) -> int:
    written = export_json_schemas(args.output_dir)
    print(f"wrote {len(written)} schemas to {args.output_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="matchlens")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    info = commands.add_parser("info", help="show the active runtime modes")
    info.set_defaults(handler=run_info)

    schemas = commands.add_parser("schemas", help="data contract schemas")
    schema_commands = schemas.add_subparsers(dest="schemas_command", required=True)
    schemas_export = schema_commands.add_parser("export", help="write JSON Schema files")
    schemas_export.add_argument("--output-dir", type=Path, default=DEFAULT_SCHEMAS_DIR)
    schemas_export.set_defaults(handler=run_schemas_export)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
