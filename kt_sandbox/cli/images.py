"""``kt-sandbox images``: list the images saved from sandboxes, or remove one."""

import argparse

from kt_sandbox.cli.common import open_manager, table


def register(sub: "argparse._SubParsersAction") -> None:
    """Add the ``images`` subcommand."""
    parser = sub.add_parser("images", help="list saved images")
    parser.add_argument("--rm", metavar="IMAGE", help="remove a saved image")
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    """List saved images, or remove the one named by ``--rm``."""
    manager = open_manager()
    if args.rm:
        manager.remove_image(args.rm)
        print(f"removed {args.rm}")
        return 0
    found = manager.saved_images()
    if not found:
        print("no saved images. Save a sandbox with `kt-sandbox save NAME IMAGE`.")
        return 0
    rows = [
        [i.reference, i.source, f"{i.size_bytes / 1e6:.0f} MB", i.created]
        for i in found
    ]
    print(table(["IMAGE", "FROM", "SIZE", "CREATED"], rows))
    return 0
