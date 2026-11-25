"""``kt-sandbox doctor``: check Docker, its runtimes and the default image."""

import argparse

from kt_sandbox.cli.common import open_manager
from kt_sandbox.manager.options import DEFAULT_IMAGE


def register(sub: "argparse._SubParsersAction") -> None:
    """Add the ``doctor`` subcommand."""
    parser = sub.add_parser("doctor", help="check Docker and the sandbox image")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    """Print what the engine offers and whether the default image is present."""
    client = open_manager().client
    version = client.version()
    runtimes = sorted(client.info().get("Runtimes", {}))
    print(
        f"docker {version.get('Version', '?')} on {version.get('Os', '?')}/{version.get('Arch', '?')}"
    )
    print(f"runtimes: {', '.join(runtimes)}")
    present = bool(client.images.list(name=DEFAULT_IMAGE))
    print(
        f"default image {DEFAULT_IMAGE}: {'present' if present else 'not on this machine'}"
    )
    if not present:
        print(f"  build it: kt-sandbox build -t {DEFAULT_IMAGE}")
    return 0
