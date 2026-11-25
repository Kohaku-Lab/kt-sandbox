"""Parse ``sandbox:<server>/<path>`` handles into the path sent to the sandbox and the local copy's place."""

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from kt_sandbox.kt_plugin.errors import SandboxFileError

PREFIX = "sandbox:"
FORM = "sandbox:<server>/<path> (or sandbox:<server>//<absolute path>)"


@dataclass(frozen=True)
class Handle:
    """A parsed handle.

    ``remote`` is the path the sandbox resolves (relative means under
    ``/work``); ``local`` is the copy's path relative to the server's copy
    folder: ``work/<path>`` for a relative path, the absolute path without its
    leading ``/`` otherwise.
    """

    server: str
    remote: str
    local: PurePosixPath


def is_handle(value: Any) -> bool:
    """True for a string that starts with ``sandbox:``."""
    return isinstance(value, str) and value.startswith(PREFIX)


def parse_handle(text: str) -> Handle:
    """Split ``text`` into server and path; refuse an empty part or a ``..`` segment."""
    server, sep, path = text[len(PREFIX) :].partition("/")
    if not server or not sep or not path.strip("/"):
        raise SandboxFileError(f"{text!r} is not a sandbox file: use {FORM}")
    segments = path.replace("\\", "/").split("/")
    if ".." in segments:
        raise SandboxFileError(f"{text!r}: a sandbox path cannot hold '..'")
    parts = [s for s in segments if s not in ("", ".")]
    if path.startswith("/"):
        return Handle(server, "/" + "/".join(parts), PurePosixPath(*parts))
    return Handle(server, path, PurePosixPath("work", *parts))
