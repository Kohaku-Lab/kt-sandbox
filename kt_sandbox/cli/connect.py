"""``kt-sandbox connect``: a real terminal in a sandbox, through ``docker exec -it``."""

import argparse
import os

from kt_sandbox.cli.common import open_manager


def register(sub: "argparse._SubParsersAction") -> None:
    """Add the ``connect`` subcommand."""
    parser = sub.add_parser("connect", help="log into a sandbox with a terminal")
    parser.add_argument("name")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    """Replace this process with the sandbox shell, starting the sandbox if it is stopped."""
    argv = open_manager().connect_argv(args.name)
    os.execvp(argv[0], argv)
    return 0
