"""``kt-sandbox import``: load images from a tarball written by ``export`` or ``docker save``."""

import argparse
from collections.abc import Sequence
from pathlib import Path

from kt_sandbox.cli.common import open_manager
from kt_sandbox.manager.archive import LoadedImage

COMMAND = "import"


def register(sub: "argparse._SubParsersAction") -> None:
    """Add the ``import`` subcommand."""
    parser = sub.add_parser(COMMAND, help="load images from a .tar or .tar.gz file")
    parser.add_argument("file", help="a tarball from `kt-sandbox export`")
    parser.set_defaults(run=run)


def report(loaded: Sequence[LoadedImage]) -> list[str]:
    """Describe what was loaded and how to open it."""
    if not loaded:
        return ["the file held no images."]
    lines = [f"loaded {image.reference}" for image in loaded]
    for image in loaded:
        if not image.saved:
            lines.append(
                f"  {image.reference} was not saved by kt-sandbox, so "
                "`kt-sandbox images` does not list it."
            )
    lines.append(
        f"  open it: kt-sandbox up NEWNAME --from {loaded[0].reference} --level strict"
    )
    return lines


def run(args: argparse.Namespace) -> int:
    """Load the tarball and print the loaded references."""
    loaded = open_manager().import_images(Path(args.file))
    print("\n".join(report(loaded)))
    return 0
