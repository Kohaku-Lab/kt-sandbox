"""Image tarballs on disk: write one, plain or gzip, and describe what loading one gave."""

import gzip
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from kt_sandbox.errors import ManagerError

GZIP_SUFFIXES = (".gz", ".tgz")
GZIP_LEVEL = 6
TAR_SUFFIXES = (".tar", ".tar.gz", ".tgz")


@dataclass(frozen=True)
class LoadedImage:
    """An image ``import`` loaded, and whether kt-sandbox saved it."""

    reference: str
    saved: bool


def wants_gzip(path: Path) -> bool:
    """Return whether ``path`` names a gzip-compressed file."""
    return path.name.lower().endswith(GZIP_SUFFIXES)


def check_destination(path: Path, *, force: bool = False) -> None:
    """Refuse a destination that exists (unless ``force``) or whose folder does not."""
    if path.exists() and not force:
        raise ManagerError(f"{path} exists; pass --force to overwrite it.")
    if path.is_dir():
        raise ManagerError(f"{path} is a folder; name a file such as image.tar.gz.")
    if not path.parent.is_dir():
        raise ManagerError(f"folder {path.parent} does not exist.")


def check_source(path: Path) -> None:
    """Refuse a tarball to load that is missing or not named ``.tar`` / ``.tar.gz``."""
    if not path.is_file():
        raise ManagerError(f"no file {path}.")
    if not path.name.lower().endswith(TAR_SUFFIXES):
        raise ManagerError(f"{path} is not a .tar or .tar.gz file.")


def write_chunks(chunks: Iterable[bytes], path: Path, *, force: bool = False) -> int:
    """Write ``chunks`` to ``path`` (gzip when it ends in ``.gz``); return its size in bytes.

    The data goes to a temporary file next to ``path`` that replaces it only when
    every chunk is written, so a failed export leaves no partial file.
    """
    check_destination(path, force=force)
    partial = path.with_name(f".{path.name}.partial")
    try:
        with open(partial, "wb") as raw:
            if wants_gzip(path):
                with gzip.GzipFile(
                    filename="", mode="wb", fileobj=raw, compresslevel=GZIP_LEVEL
                ) as packed:
                    for chunk in chunks:
                        packed.write(chunk)
            else:
                for chunk in chunks:
                    raw.write(chunk)
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)
    return path.stat().st_size
