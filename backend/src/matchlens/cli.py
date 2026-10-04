import argparse
from collections.abc import Sequence

from matchlens import __version__
from matchlens.config import get_settings


def run_info(_: argparse.Namespace) -> int:
    settings = get_settings()
    print(f"matchlens {__version__}")
    print(f"llm_mode={settings.llm_mode}")
    print(f"transport={settings.transport}")
    print(f"store={settings.store}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="matchlens")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    info = commands.add_parser("info", help="show the active runtime modes")
    info.set_defaults(handler=run_info)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
