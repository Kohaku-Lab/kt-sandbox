"""Find where a sandbox's files come from, using KohakuTerrarium's global MCP registry (``mcp_servers.yaml``)."""

import os
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any

import yaml

from kohakuterrarium.utils.env_interp import ENV_VAR_PATTERN, interpolate_env_vars

from kt_sandbox.kt_plugin.errors import SandboxFileError

try:
    from kohakuterrarium.core.mcp_registry import load_global_mcp_servers
except ImportError:  # pragma: no cover - a KohakuTerrarium without the core reader
    load_global_mcp_servers = None

HTTP_TRANSPORTS = {"streamable_http", "streamable-http", "http", "sse"}
SERVER_COMMAND = "kt-sandbox-mcp"
DOCKER_FLAGS_WITH_VALUE = {
    "-e",
    "--env",
    "--env-file",
    "-u",
    "--user",
    "-w",
    "--workdir",
    "--detach-keys",
}


@dataclass(frozen=True)
class HttpSource:
    """A sandbox served over HTTP: files come from ``<url>/files`` with ``headers``."""

    server: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def files_url(self) -> str:
        return self.url.rstrip("/") + "/files"


@dataclass(frozen=True)
class DockerSource:
    """A sandbox reached by ``docker exec``: files come from ``kt-sandbox-file`` in ``container``."""

    server: str
    docker: str
    container: str
    env: dict[str, str] = field(default_factory=dict)


def _load_entries() -> list[Any]:
    if load_global_mcp_servers is not None:
        return load_global_mcp_servers()
    directory = os.environ.get("KT_CONFIG_DIR") or os.path.expanduser(
        "~/.kohakuterrarium"
    )
    path = os.path.join(directory, "mcp_servers.yaml")
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return []
    return data if isinstance(data, list) else []


def _expand(value: Any, where: str, server: str) -> Any:
    """``value`` with ``${VAR}`` / ``${VAR:default}`` expanded; an unset ``${VAR}`` is refused."""
    match value:
        case str():
            texts = [value]
        case dict():
            texts = [str(v) for v in value.values()]
        case list():
            texts = [str(v) for v in value]
        case _:
            return value
    for text in texts:
        for found in ENV_VAR_PATTERN.finditer(text):
            if found.group(2) is None and found.group(1) not in os.environ:
                raise SandboxFileError(
                    f"MCP server {server}: environment variable {found.group(1)} "
                    f"is not set (used in {where})"
                )
    return interpolate_env_vars(value)


def _strings(value: Any, where: str, server: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SandboxFileError(
            f"MCP server {server}: {where} must be a list of strings"
        )
    return list(value)


def _mapping(value: Any, where: str, server: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SandboxFileError(f"MCP server {server}: {where} must be a mapping")
    return {str(k): str(v) for k, v in value.items()}


def _container(args: list[str]) -> str | None:
    """The container of ``exec [flags] <container> kt-sandbox-mcp ...``, else None."""
    if not args or args[0] != "exec":
        return None
    rest = args[1:]
    index = 0
    while index < len(rest) and rest[index].startswith("-"):
        flag = rest[index]
        index += 2 if flag in DOCKER_FLAGS_WITH_VALUE else 1
    if index + 1 >= len(rest):
        return None
    if PurePath(rest[index + 1]).name != SERVER_COMMAND:
        return None
    return rest[index]


def _docker_source(entry: dict, server: str) -> DockerSource:
    command = str(_expand(entry.get("command") or "", "command", server))
    args = _expand(_strings(entry.get("args"), "args", server), "args", server)
    env = _expand(_mapping(entry.get("env"), "env", server), "env", server)
    container = None
    if PurePath(command).name.lower() in ("docker", "docker.exe"):
        container = _container(args)
    if container is None:
        raise SandboxFileError(
            f"MCP server {server} is a stdio server but not "
            f"`docker exec -i <container> {SERVER_COMMAND}`, so its files cannot "
            "be fetched; register it with `kt-sandbox mcp <sandbox> --register`"
        )
    return DockerSource(server=server, docker=command, container=container, env=env)


def _http_source(entry: dict, server: str) -> HttpSource:
    url = entry.get("url")
    if not isinstance(url, str) or not url:
        raise SandboxFileError(f"MCP server {server} has no url")
    headers = _mapping(entry.get("headers"), "headers", server)
    return HttpSource(
        server=server,
        url=_expand(url, "url", server),
        headers=_expand(headers, "headers", server),
    )


def find_source(server: str) -> HttpSource | DockerSource:
    """The file source of registry server ``server``; raise :class:`SandboxFileError` when it has none."""
    for entry in _load_entries():
        if isinstance(entry, dict) and entry.get("name") == server:
            break
    else:
        raise SandboxFileError(
            f"no MCP server named {server!r} in KohakuTerrarium's MCP settings"
        )
    transport = str(entry.get("transport") or "stdio").lower()
    if transport == "stdio":
        return _docker_source(entry, server)
    if transport in HTTP_TRANSPORTS:
        return _http_source(entry, server)
    raise SandboxFileError(
        f"MCP server {server} uses transport {transport!r}; a sandbox's files "
        "need streamable_http, http, sse or stdio"
    )
