"""The ``kt-sandbox`` command: argparse entry point and subcommand dispatch."""

import argparse
import sys
from collections.abc import Sequence

from kt_sandbox import __version__
from kt_sandbox.cli import (
    build,
    connect,
    doctor,
    down,
    export,
    images,
    import_,
    levels,
    ls,
    mcp,
    proxy,
    rm,
    save,
    up,
    upgrade,
)
from kt_sandbox.errors import SandboxError

COMMANDS = (
    up,
    down,
    ls,
    rm,
    connect,
    save,
    images,
    export,
    import_,
    levels,
    mcp,
    doctor,
    build,
    proxy,
    upgrade,
)


def build_parser() -> argparse.ArgumentParser:
    """Return the parser with every subcommand registered."""
    parser = argparse.ArgumentParser(
        prog="kt-sandbox",
        description="Open, log into, save and lock down persistent sandboxes.",
    )
    parser.add_argument(
        "--version", action="version", version=f"kt-sandbox {__version__}"
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    for module in COMMANDS:
        module.register(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command in ``argv`` (default: ``sys.argv``) and return its exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "run", None):
        parser.print_help(sys.stderr)
        return 2
    try:
        return args.run(args)
    except SandboxError as exc:
        print(f"kt-sandbox: {exc}", file=sys.stderr)
        return 1
