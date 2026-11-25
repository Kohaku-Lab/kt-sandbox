"""Sandbox containers: create, find, list; Docker labels are the registry."""

from dataclasses import dataclass
from typing import Any

import docker
from docker.errors import APIError, NotFound
from docker.models.containers import Container

from kt_sandbox.errors import ManagerError
from kt_sandbox.manager.options import (
    LABEL_LEVEL,
    LABEL_NAME,
    LABEL_SUDO,
    MCP_PORT,
    container_name,
)


@dataclass(frozen=True)
class SandboxInfo:
    """A sandbox as ``ls`` shows it."""

    name: str
    level: str
    sudo: bool
    state: str
    image: str
    container: str
    port: int | None


def _published_port(container: Container) -> int | None:
    bindings = (container.attrs.get("NetworkSettings", {}).get("Ports") or {}).get(
        f"{MCP_PORT}/tcp"
    )
    return int(bindings[0]["HostPort"]) if bindings else None


def info_of(container: Container) -> SandboxInfo:
    """Describe a sandbox container from its labels and state."""
    labels = container.labels
    tags = container.image.tags if container.image else []
    return SandboxInfo(
        name=labels.get(LABEL_NAME, container.name),
        level=labels.get(LABEL_LEVEL, "?"),
        sudo=labels.get(LABEL_SUDO) == "true",
        state=container.status,
        image=tags[0] if tags else container.attrs.get("Config", {}).get("Image", "?"),
        container=container.name,
        port=_published_port(container),
    )


def find(client: docker.DockerClient, name: str) -> Container | None:
    """Return the container of sandbox ``name``, or None."""
    try:
        return client.containers.get(container_name(name))
    except NotFound:
        return None


def require(client: docker.DockerClient, name: str) -> Container:
    """Return the container of sandbox ``name`` or raise saying how to see what exists."""
    container = find(client, name)
    if container is None:
        raise ManagerError(f"no sandbox named {name!r}. See `kt-sandbox ls`.")
    return container


def list_all(client: docker.DockerClient) -> list[SandboxInfo]:
    """Return every sandbox, running or stopped, ordered by name."""
    found = client.containers.list(all=True, filters={"label": LABEL_NAME})
    return sorted((info_of(c) for c in found), key=lambda info: info.name)


def create(client: docker.DockerClient, options: dict[str, Any]) -> Container:
    """Create a container from ``options``; Docker's refusal becomes a :class:`ManagerError`."""
    try:
        return client.containers.create(**options)
    except APIError as exc:
        raise ManagerError(
            f"Docker refused to create the sandbox: {exc.explanation or exc}"
        ) from exc
