"""``kt-sandbox upgrade``: put this kt-sandbox into existing sandboxes."""

import argparse
import sys

from kt_sandbox import __version__
from kt_sandbox.cli.common import open_manager
from kt_sandbox.errors import ManagerError


def register(sub: "argparse._SubParsersAction") -> None:
    """Add the ``upgrade`` subcommand."""
    parser = sub.add_parser(
        "upgrade",
        help="put this kt-sandbox's server and commands into a sandbox",
        description="Replace the kt-sandbox package and commands inside a sandbox "
        "with the installed ones; the sandbox may be running or stopped.",
    )
    parser.add_argument("name", nargs="?", help="the sandbox to upgrade")
    parser.add_argument("--all", action="store_true", help="upgrade every sandbox")
    parser.set_defaults(run=run, parser=parser)


def _report(done) -> None:
    print(
        f"upgraded {done.name} to kt-sandbox {__version__}: {done.files} package "
        f"files, commands {', '.join(done.wrappers)}"
    )
    if not done.checked:
        print(
            "  The sandbox is stopped, so its dependencies were not checked; "
            f"run `kt-sandbox upgrade {done.name}` again once it runs to check them."
        )
    print(
        "  Restart the sandbox's MCP server to use it: docker exec "
        f"{done.container} pkill -f 'kt-sandbox-mcp|kt_sandbox.server', then start it again "
        "(stdio servers restart on the next connection)."
    )


def run(args: argparse.Namespace) -> int:
    """Upgrade one sandbox or all of them; fail if any was refused."""
    if bool(args.name) == bool(args.all):
        args.parser.print_usage(sys.stderr)
        print("kt-sandbox upgrade: name one sandbox or pass --all", file=sys.stderr)
        return 2
    manager = open_manager()
    if args.name:
        _report(manager.upgrade(args.name))
        return 0
    failed = 0
    for name, result in manager.upgrade_all():
        if isinstance(result, ManagerError):
            failed += 1
            print(f"kt-sandbox: {name}: {result}", file=sys.stderr)
        else:
            _report(result)
    return 1 if failed else 0
