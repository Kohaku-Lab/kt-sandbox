"""The operations a person runs: open, stop, remove, list, save, export, import and reconnect sandboxes."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import docker

from kt_sandbox.errors import ManagerError
from kt_sandbox.levels.presets import DEFAULT_LEVEL, build_level
from kt_sandbox.manager import archive
from kt_sandbox.manager.docker import containers, images, network
from kt_sandbox.manager.options import (
    DEFAULT_IMAGE,
    LABEL_NET,
    SANDBOX_USER,
    MCP_PORT,
    WORKDIR,
    Mount,
    container_name,
    container_options,
)

STOP_TIMEOUT_S = 10


@dataclass(frozen=True)
class UpResult:
    """What ``up`` did: ``created`` a new sandbox, ``started`` a stopped one, or found it ``running``."""

    info: containers.SandboxInfo
    action: str


class Manager:
    """Sandbox operations over one Docker client."""

    def __init__(self, client: docker.DockerClient):
        self.client = client

    def up(
        self,
        name: str,
        *,
        level_name: str | None = None,
        image: str = DEFAULT_IMAGE,
        overrides: Mapping[str, Any] | None = None,
        mounts: tuple[Mount, ...] = (),
        env: dict[str, str] | None = None,
        publish: int | None = None,
    ) -> UpResult:
        """Create sandbox ``name`` at ``level_name`` from ``image`` and start it.

        A new sandbox without ``level_name`` gets the default level. A sandbox
        that already exists is started if stopped. It keeps the level it was
        created with; naming a different one is refused. To change the level, save
        it and open the image as a new sandbox.
        """
        existing = containers.find(self.client, name)
        if existing is not None:
            info = containers.info_of(existing)
            if level_name is not None and info.level != level_name:
                raise ManagerError(
                    f"sandbox {name!r} already exists at level {info.level!r}. To use "
                    f"{level_name!r}, save it (`kt-sandbox save {name} <image>`) and open "
                    f"that image as a new sandbox with `--from <image> --level {level_name}`."
                )
            if existing.status == "running":
                return UpResult(info, "running")
            if existing.labels.get(LABEL_NET) == "allowlist":
                proxy = network.ensure_egress(self.client, image)
                network.ensure_sandbox_network(self.client, name, proxy)
                network.sync_policy(self.client)
            existing.start()
            existing.reload()
            return UpResult(containers.info_of(existing), "started")
        level_name = level_name or DEFAULT_LEVEL
        level = build_level(level_name, overrides)
        images.ensure(self.client, image)
        secret = network.prepare(self.client, level, image, name)
        options = container_options(
            name,
            level_name,
            level,
            image=image,
            mounts=mounts,
            env=env,
            publish=publish,
            egress_secret=secret,
        )
        container = containers.create(self.client, options)
        try:
            network.sync_policy(self.client)
            container.start()
        except Exception:
            container.remove(force=True, v=True)
            network.remove_sandbox_network(self.client, name)
            raise
        container.reload()
        return UpResult(containers.info_of(container), "created")

    def down(self, name: str) -> containers.SandboxInfo:
        """Stop a sandbox, keeping its files and installed packages."""
        container = containers.require(self.client, name)
        container.stop(timeout=STOP_TIMEOUT_S)
        container.reload()
        return containers.info_of(container)

    def rm(self, name: str, *, force: bool = False) -> None:
        """Remove a sandbox and its state. A running sandbox needs ``force``."""
        container = containers.require(self.client, name)
        if container.status == "running" and not force:
            raise ManagerError(
                f"sandbox {name!r} is running. Stop it with `kt-sandbox down {name}`, or use --force."
            )
        container.remove(force=force, v=True)
        network.remove_sandbox_network(self.client, name)
        if not network.prune_egress(self.client):
            network.sync_policy(self.client)

    def ls(self) -> list[containers.SandboxInfo]:
        """List every sandbox."""
        return containers.list_all(self.client)

    def save(self, name: str, reference: str) -> images.SavedImage:
        """Save the sandbox's state as image ``reference``, ready to open at any level."""
        return images.commit(
            self.client, containers.require(self.client, name), reference
        )

    def saved_images(self) -> list[images.SavedImage]:
        """List the images saved from sandboxes."""
        return images.saved(self.client)

    def remove_image(self, reference: str) -> None:
        """Delete a saved image."""
        images.remove(self.client, reference)

    def export_image(self, reference: str, path: Path, *, force: bool = False) -> int:
        """Write image ``reference`` to the tarball ``path``; return its size in bytes."""
        return images.export(self.client, reference, path, force=force)

    def import_images(self, path: Path) -> list[archive.LoadedImage]:
        """Load the images in the tarball ``path``."""
        return images.load(self.client, path)

    def _running(self, name: str):
        container = containers.require(self.client, name)
        if container.status != "running":
            container.start()
            container.reload()
        return container

    def connect_argv(self, name: str) -> list[str]:
        """Return the command that opens a terminal in the sandbox, starting it if stopped."""
        container = self._running(name)
        return [
            "docker",
            "exec",
            "-it",
            "-u",
            SANDBOX_USER,
            "-w",
            WORKDIR,
            container.name,
            "bash",
        ]

    def mcp_config(self, name: str) -> dict[str, Any]:
        """Return a KohakuTerrarium ``mcp_servers`` entry that runs the sandbox's MCP server over stdio."""
        container = self._running(name)
        return {
            "name": f"sandbox-{name}",
            "transport": "stdio",
            "command": "docker",
            "args": ["exec", "-i", container.name, "kt-sandbox-mcp"],
        }

    def http_hint(self, name: str) -> str:
        """Return how to serve the sandbox MCP server over HTTP on its published port."""
        info = containers.info_of(containers.require(self.client, name))
        if info.port is None:
            return (
                f"sandbox {name!r} publishes no port; open it with `up --publish PORT`."
            )
        return (
            f"docker exec -d -e KT_SANDBOX_MCP_TOKEN=<token> {container_name(name)} "
            f"kt-sandbox-mcp --transport http --port {MCP_PORT}\n"
            f"then connect to http://localhost:{info.port}/mcp with 'Authorization: Bearer <token>'"
        )
