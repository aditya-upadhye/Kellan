import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from matchlens import __version__
from matchlens.config import get_settings
from matchlens.models.json_schema import export_json_schemas
from matchlens.sim.match import simulate_scenario
from matchlens.sim.output import write_match
from matchlens.sim.scenarios import UnknownScenarioError, load_scenario
from matchlens.world.meridian import MERIDIAN_LEAGUE

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


def run_sim(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        scenario = load_scenario(args.scenario, settings.scenarios_dir)
    except UnknownScenarioError as error:
        print(error, file=sys.stderr)
        return 2
    started = time.perf_counter()
    match = simulate_scenario(
        MERIDIAN_LEAGUE, scenario, args.seed, with_tracking=not args.events_only
    )
    elapsed_s = time.perf_counter() - started
    match_dir = write_match(match, args.output_dir or settings.samples_dir)
    metadata, score = match.metadata, match.score
    print(
        f"{metadata.match_id}: {metadata.home.name} {score['home']}-{score['away']} "
        f"{metadata.away.name} | {len(match.events)} events, {len(match.frames)} frames "
        f"generated in {elapsed_s:.2f} s"
    )
    print(f"written to {match_dir}")
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

    sim = commands.add_parser("sim", help="simulate a scenario and write the match files")
    sim.add_argument("--scenario", required=True)
    sim.add_argument("--seed", type=int, required=True)
    sim.add_argument("--output-dir", type=Path, default=None)
    sim.add_argument("--events-only", action="store_true", help="skip tracking frames")
    sim.set_defaults(handler=run_sim)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
