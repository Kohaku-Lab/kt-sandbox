"""``kt-sandbox rm``: remove a sandbox and its state (save it first to keep it)."""

import argparse

from kt_sandbox.cli.common import open_manager


def register(sub: "argparse._SubParsersAction") -> None:
    """Add the ``rm`` subcommand."""
    parser = sub.add_parser("rm", help="remove a sandbox and its state")
    parser.add_argument("name")
    parser.add_argument("--force", action="store_true", help="remove a running sandbox")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    """Remove the sandbox."""
    open_manager().rm(args.name, force=args.force)
    print(f"sandbox {args.name}: removed")
    return 0
