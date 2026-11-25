"""``kt-sandbox export``: write an image to a tarball, to move it to another host."""

import argparse
from pathlib import Path

from kt_sandbox.cli.common import open_manager


def register(sub: "argparse._SubParsersAction") -> None:
    """Add the ``export`` subcommand."""
    parser = sub.add_parser("export", help="write an image to a .tar or .tar.gz file")
    parser.add_argument("image", help="the image, for example lab-image or lab:v2")
    parser.add_argument("file", help="the tarball; a name ending in .gz is gzipped")
    parser.add_argument(
        "--force", action="store_true", help="overwrite FILE if it exists"
    )
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    """Export the image and print the file's size."""
    path = Path(args.file)
    size = open_manager().export_image(args.image, path, force=args.force)
    print(f"exported {args.image} to {path} ({size / 1e6:.0f} MB)")
    print(f"  load it on another host: kt-sandbox import {path.name}")
    return 0
