"""``kt-sandbox-about``: print what this sandbox has, read from the running container."""

import argparse
import os
import sys
from collections.abc import Sequence

from kt_sandbox import __version__
from kt_sandbox.server.about.document import render
from kt_sandbox.server.settings import ServerSettings


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of ``kt-sandbox-about``."""
    parser = argparse.ArgumentParser(
        prog="kt-sandbox-about",
        description=(
            "Print what this sandbox has as Markdown: its level's policy, live "
            "usage, image tiers, programs and Python packages."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"kt-sandbox {__version__}"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Print the document; values that cannot be read show as unknown."""
    build_parser().parse_args(argv)
    try:
        settings = ServerSettings.from_env()
    except ValueError as exc:
        print(f"kt-sandbox-about: {exc}; the policy shows as unknown", file=sys.stderr)
        workdir = os.environ.get("KT_SANDBOX_WORKDIR", "")
        settings = ServerSettings.from_env({"KT_SANDBOX_WORKDIR": workdir})
    sys.stdout.write(render(settings))
    return 0
