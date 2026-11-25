"""``kt-sandbox proxy``: run the egress proxy the allowlist level routes through."""

import argparse
import asyncio
import logging
from pathlib import Path

from kt_sandbox.proxy.policy import Policy
from kt_sandbox.proxy.server import DEFAULT_MAX_BYTES, serve

DEFAULT_PORT = 3128
DEFAULT_POLICY = "/etc/kt-sandbox/egress.json"


def register(sub: "argparse._SubParsersAction") -> None:
    """Add the ``proxy`` subcommand."""
    parser = sub.add_parser(
        "proxy", help="run the egress proxy (started for you by `up`)"
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--policy",
        default=DEFAULT_POLICY,
        help="JSON file of sandboxes and their hosts",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=DEFAULT_MAX_BYTES,
        help="byte budget per connection",
    )
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    """Serve the allowlist proxy until stopped."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    policy = Policy(Path(args.policy))
    try:
        asyncio.run(serve(policy, args.host, args.port, max_bytes=args.max_bytes))
    except KeyboardInterrupt:
        pass
    return 0
