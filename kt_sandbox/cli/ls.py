"""``kt-sandbox ls``: list sandboxes with their level and state."""

import argparse

from kt_sandbox.cli.common import open_manager, table


def register(sub: "argparse._SubParsersAction") -> None:
    """Add the ``ls`` subcommand."""
    parser = sub.add_parser("ls", help="list sandboxes")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    """Print one line per sandbox."""
    infos = open_manager().ls()
    if not infos:
        print("no sandboxes. Open one with `kt-sandbox up NAME`.")
        return 0
    rows = [
        [
            i.name,
            i.level,
            i.state,
            "yes" if i.sudo else "no",
            str(i.port or "-"),
            i.image,
        ]
        for i in infos
    ]
    print(table(["NAME", "LEVEL", "STATE", "SUDO", "PORT", "IMAGE"], rows))
    return 0
