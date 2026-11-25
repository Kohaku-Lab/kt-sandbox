"""``kt-sandbox up``: open a sandbox at a security level, or start a stopped one."""

import argparse

from kt_sandbox.cli.common import open_manager
from kt_sandbox.levels.presets import DEFAULT_LEVEL, LEVELS
from kt_sandbox.manager.options import DEFAULT_IMAGE, parse_mount, validate_name


def register(sub: "argparse._SubParsersAction") -> None:
    """Add the ``up`` subcommand."""
    parser = sub.add_parser("up", help="open a sandbox (or start a stopped one)")
    parser.add_argument("name")
    parser.add_argument(
        "--level",
        choices=sorted(LEVELS),
        default=None,
        help=f"for a new sandbox (default: {DEFAULT_LEVEL}); an existing one keeps its level",
    )
    parser.add_argument(
        "--from",
        dest="image",
        default=None,
        help="image to open (default: the slim sandbox image)",
    )
    parser.add_argument("--network", choices=("none", "allowlist", "open"))
    parser.add_argument(
        "--allow", action="append", metavar="HOST", help="allowlist host; repeatable"
    )
    parser.add_argument("--cpus", type=float)
    parser.add_argument("--memory", metavar="SIZE", help="for example 512m or 2g")
    parser.add_argument("--pids", type=int)
    parser.add_argument(
        "--wall", type=int, metavar="SECONDS", help="longest one command may run"
    )
    parser.add_argument(
        "--runtime",
        metavar="NAME",
        help="container runtime: any runtime installed in your Docker engine",
    )
    parser.add_argument(
        "--read-only", action="store_true", help="read-only root filesystem"
    )
    parser.add_argument("--mount", action="append", default=[], metavar="SRC:DST[:ro]")
    parser.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument(
        "--publish",
        type=int,
        metavar="PORT",
        help="publish the MCP port on this host port",
    )
    parser.set_defaults(run=run)


def overrides_from(args: argparse.Namespace) -> dict:
    """Collect the level fields the user set on the command line."""
    overrides: dict = {}
    for field in ("network", "runtime"):
        if getattr(args, field):
            overrides[field] = getattr(args, field)
    if args.allow:
        overrides["allow"] = args.allow
        overrides.setdefault("network", "allowlist")
    if args.read_only:
        overrides["read_only"] = True
    limits = {
        key: value
        for key, value in (
            ("cpus", args.cpus),
            ("memory", args.memory),
            ("pids", args.pids),
            ("wall_s", args.wall),
        )
        if value is not None
    }
    if limits:
        overrides["limits"] = limits
    return overrides


def run(args: argparse.Namespace) -> int:
    """Open the sandbox and say how to reach it."""
    validate_name(args.name)
    env = dict(item.split("=", 1) for item in args.env if "=" in item)
    result = open_manager().up(
        args.name,
        level_name=args.level,
        image=args.image or DEFAULT_IMAGE,
        overrides=overrides_from(args),
        mounts=tuple(parse_mount(spec) for spec in args.mount),
        env=env,
        publish=args.publish,
    )
    info = result.info
    print(
        f"sandbox {info.name}: {result.action} (level {info.level}, image {info.image})"
    )
    print(f"  log in:   kt-sandbox connect {info.name}")
    print(f"  for KT:   kt-sandbox mcp {info.name}")
    return 0
