"""``kt-sandbox build``: build the sandbox image from tiers and extra packages."""

import argparse

from kt_sandbox.manager import builder
from kt_sandbox.manager.options import DEFAULT_IMAGE


def register(sub: "argparse._SubParsersAction") -> None:
    """Add the ``build`` subcommand."""
    parser = sub.add_parser(
        "build", help="build a sandbox image from tiers and packages"
    )
    parser.add_argument(
        "-t", "--tag", default=DEFAULT_IMAGE, help=f"default: {DEFAULT_IMAGE}"
    )
    parser.add_argument(
        "--extras",
        default="",
        help="comma-separated tiers on top of slim: data, render, dev, media, browser",
    )
    parser.add_argument("--apt", action="append", default=[], metavar="PACKAGE")
    parser.add_argument("--pip", action="append", default=[], metavar="PACKAGE")
    parser.add_argument("--base", help="base image (default python:3.12-slim)")
    parser.add_argument(
        "--platform", help="for example linux/amd64,linux/arm64 (uses buildx)"
    )
    parser.add_argument(
        "--push", action="store_true", help="push after building (uses buildx)"
    )
    parser.set_defaults(run=run)


def run(args: argparse.Namespace) -> int:
    """Build the image and return Docker's exit code."""
    return builder.build(
        tag=args.tag,
        extras=[tier for tier in args.extras.split(",") if tier],
        apt=args.apt,
        pip=args.pip,
        base=args.base,
        platform=args.platform,
        push=args.push,
    )
