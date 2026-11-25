"""Add a sandbox to KohakuTerrarium's global MCP server list, ``mcp_servers.yaml``.

The file is a YAML list of server entries in KohakuTerrarium's config folder:
``$KT_CONFIG_DIR``, or ``~/.kohakuterrarium``. This module writes the same
format without importing KohakuTerrarium, and leaves every other entry as it is.
"""

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from kt_sandbox.errors import ManagerError

FILE_NAME = "mcp_servers.yaml"
DEFAULT_DIR = "~/.kohakuterrarium"


def registry_path(environ: Mapping[str, str] | None = None) -> Path:
    """Return where KohakuTerrarium keeps its global MCP server list."""
    env = os.environ if environ is None else environ
    return Path(env.get("KT_CONFIG_DIR") or DEFAULT_DIR).expanduser() / FILE_NAME


def load(path: Path) -> list[dict[str, Any]]:
    """Return the entries in ``path``; a missing or empty file has none.

    A file that is not a YAML list of mappings is refused rather than replaced.
    """
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError, OSError) as exc:
        raise ManagerError(
            f"cannot read {path} ({exc}). Fix or move that file, then run this again."
        ) from exc
    if data is None:
        return []
    if not isinstance(data, list) or not all(isinstance(e, dict) for e in data):
        raise ManagerError(
            f"{path} is not a list of MCP servers. Fix or move that file, then run "
            "this again."
        )
    return data


def _write_atomically(path: Path, servers: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        servers, default_flow_style=False, sort_keys=False, allow_unicode=True
    )
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{FILE_NAME}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o7777)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def upsert(entry: dict[str, Any], path: Path | None = None) -> tuple[Path, bool]:
    """Put ``entry`` in the list, replacing any entry of the same name in place.

    Returns the file's path and whether an entry was replaced.
    """
    path = path or registry_path()
    servers: list[dict[str, Any]] = []
    replaced = False
    for server in load(path):
        if server.get("name") != entry["name"]:
            servers.append(server)
        elif not replaced:
            servers.append(entry)
            replaced = True
    if not replaced:
        servers.append(entry)
    _write_atomically(path, servers)
    return path, replaced
