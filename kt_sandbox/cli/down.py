"""``kt-sandbox down``: stop a sandbox, keeping its files and installed packages."""

import argparse

from kt_sandbox.cli.common import open_manager


def register(sub: "argparse._SubParsersAction") -> None:
    """Add the ``down`` subcommand."""
    parser = sub.add_parser("down", help="stop a sandbox (its state is kept)")
    parser.add_argument("name")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    """Stop the sandbox."""
    info = open_manager().down(args.name)
    print(f"sandbox {info.name}: {info.state}")
    return 0
