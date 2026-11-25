"""``kt-sandbox mcp``: print, or register, the config that lets a KohakuTerrarium agent reach a sandbox."""

import argparse

from kt_sandbox.cli.common import open_manager
from kt_sandbox.errors import ManagerError


def register(sub: "argparse._SubParsersAction") -> None:
    """Add the ``mcp`` subcommand."""
    parser = sub.add_parser(
        "mcp", help="print the KT config for a sandbox's MCP server"
    )
    parser.add_argument("name")
    route = parser.add_mutually_exclusive_group()
    route.add_argument(
        "--http", action="store_true", help="show the HTTP route instead of stdio"
    )
    route.add_argument(
        "--register",
        action="store_true",
        help="add the stdio entry to KohakuTerrarium's global MCP server list",
    )
    parser.set_defaults(run=run)


def print_entry(entry: dict) -> None:
    """Print ``entry`` as a ready-to-paste ``mcp_servers`` block."""
    print("mcp_servers:")
    print(f"  - name: {entry['name']}")
    print(f"    transport: {entry['transport']}")
    print(f"    command: {entry['command']}")
    print(f"    args: [{', '.join(entry['args'])}]")


def run(args: argparse.Namespace) -> int:
    """Print a ready-to-paste ``mcp_servers`` entry, the HTTP steps, or register the entry."""
    manager = open_manager()
    if args.http:
        print(manager.http_hint(args.name))
        return 0
    entry = manager.mcp_config(args.name)
    if not args.register:
        print_entry(entry)
        return 0
    # pyyaml is part of the manager extra, like docker; open_manager has already
    # checked that extra, so this import only fails on a partial install.
    try:
        from kt_sandbox.manager import kt_config
    except ImportError as exc:
        raise ManagerError(
            'registering needs pyyaml: pip install "kt-sandbox[manager]"'
        ) from exc
    path, replaced = kt_config.upsert(entry)
    command = " ".join([entry["command"], *entry["args"]])
    print(
        f"{'updated' if replaced else 'registered'} {entry['name']} "
        f"({entry['transport']}: {command})"
    )
    print(f"in {path}")
    return 0
