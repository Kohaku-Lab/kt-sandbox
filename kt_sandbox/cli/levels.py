"""``kt-sandbox levels``: show what each security level sets."""

import argparse

from kt_sandbox.cli.common import table
from kt_sandbox.levels.presets import LEVELS, build_level


def register(sub: "argparse._SubParsersAction") -> None:
    """Add the ``levels`` subcommand."""
    parser = sub.add_parser("levels", help="show the security levels")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    """Print one row per level: network, sudo and limits."""
    rows = []
    for name in LEVELS:
        level = build_level(name)
        network = level.network
        if level.allow:
            network += f" ({len(level.allow)} hosts)"
        limits = level.limits
        rows.append(
            [
                name,
                network,
                "yes" if level.sudo else "no",
                str(limits.cpus),
                limits.memory,
                str(limits.pids),
                f"{limits.wall_s} s",
            ]
        )
    print(
        table(
            ["LEVEL", "NETWORK", "SUDO", "CPUS", "MEMORY", "PIDS", "COMMAND TIME"], rows
        )
    )
    return 0
