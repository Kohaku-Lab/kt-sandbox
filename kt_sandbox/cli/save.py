"""``kt-sandbox save``: save a sandbox's state as an image to open again at any level."""

import argparse

from kt_sandbox.cli.common import open_manager


def register(sub: "argparse._SubParsersAction") -> None:
    """Add the ``save`` subcommand."""
    parser = sub.add_parser("save", help="save a sandbox as an image")
    parser.add_argument("name")
    parser.add_argument("image", help="name for the image, for example lab or lab:v2")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    """Commit the sandbox and say how to open the result."""
    saved = open_manager().save(args.name, args.image)
    print(f"saved {args.name} as {saved.reference} ({saved.size_bytes / 1e6:.0f} MB)")
    print(
        f"  open it again: kt-sandbox up NEWNAME --from {saved.reference} --level strict"
    )
    return 0
