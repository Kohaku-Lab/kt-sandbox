"""Turn a level into container settings: limits, network, user, labels, environment."""

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from kt_sandbox.errors import ManagerError
from kt_sandbox.levels.models import Level

DEFAULT_IMAGE = os.environ.get("KT_SANDBOX_IMAGE", "ghcr.io/kohaku-lab/kt-sandbox:slim")
WORKDIR = "/work"
SANDBOX_USER = "sandbox"
MCP_PORT = 8765
LABEL_NAME = "kt-sandbox.name"
LABEL_LEVEL = "kt-sandbox.level"
LABEL_SUDO = "kt-sandbox.sudo"
LABEL_NET = "kt-sandbox.network"
LABEL_ALLOW = "kt-sandbox.allow"
LABEL_EGRESS = "kt-sandbox.egress"
EGRESS_POLICY_DIR = "/etc/kt-sandbox"
EGRESS_POLICY_FILE = "egress.json"
SECRET_ENV = "KT_SANDBOX_EGRESS_SECRET"
LABEL_SAVED = "kt-sandbox.saved"
NETWORK_PREFIX = "kt-sandbox-net-"
EGRESS_NAME = "kt-sandbox-egress"
EGRESS_PORT = 3128
PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")

_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,39}$")


@dataclass(frozen=True)
class Mount:
    """A host folder made visible inside the sandbox."""

    source: str
    target: str
    read_only: bool = False


def validate_name(name: str) -> str:
    """Return ``name`` if it is a usable sandbox name, else raise with the rule."""
    if not _NAME.match(name):
        raise ManagerError(
            f"{name!r} is not a valid sandbox name; use 1-40 lowercase letters, "
            "digits, '-', '_' or '.', starting with a letter or digit."
        )
    return name


def network_name(name: str) -> str:
    """Return the name of the private internal network of allowlist sandbox ``name``."""
    return f"{NETWORK_PREFIX}{validate_name(name)}"


def container_name(name: str) -> str:
    """Return the Docker container name of sandbox ``name``."""
    return f"kt-sandbox-{validate_name(name)}"


def parse_mount(spec: str) -> Mount:
    """Parse ``SOURCE:TARGET`` or ``SOURCE:TARGET:ro`` into a :class:`Mount`."""
    parts = spec.split(":")
    if (
        len(parts) not in (2, 3)
        or not all(parts[:2])
        or (len(parts) == 3 and parts[2] != "ro")
    ):
        raise ManagerError(f"bad mount {spec!r}; use SOURCE:TARGET or SOURCE:TARGET:ro")
    if not parts[1].startswith("/"):
        raise ManagerError(f"bad mount {spec!r}; the target must be an absolute path")
    return Mount(
        os.path.abspath(os.path.expanduser(parts[0])), parts[1], len(parts) == 3
    )


def proxy_environment(level: Level, name: str = "", secret: str = "") -> dict[str, str]:
    """Proxy variables for ``level``: the egress proxy with this sandbox's credential, or empty.

    Empty values matter: an image saved from an allowlist sandbox carries the
    proxy variables, and a sandbox reopened at another level must not keep them.
    """
    url = ""
    if level.network == "allowlist":
        url = f"http://{name}:{secret}@{EGRESS_NAME}:{EGRESS_PORT}"
    return {var: url for var in PROXY_VARS}


def container_options(
    name: str,
    level_name: str,
    level: Level,
    *,
    image: str,
    mounts: tuple[Mount, ...] = (),
    env: dict[str, str] | None = None,
    publish: int | None = None,
    egress_secret: str = "",
) -> dict[str, Any]:
    """Return the keyword arguments for creating the container of sandbox ``name``.

    Everything comes from the level: CPU, memory and process limits, the
    network, sudo (a sandbox without it drops every capability and sets
    no-new-privileges), the runtime and a read-only root. ``publish`` maps a
    host port to the MCP port. An allowlist sandbox needs ``egress_secret``, its
    credential at the egress proxy.
    """
    if level.network == "allowlist" and not egress_secret:
        raise ManagerError("an allowlist sandbox needs an egress credential")
    options: dict[str, Any] = {
        "image": image,
        "name": container_name(name),
        "command": ["sleep", "infinity"],
        "working_dir": WORKDIR,
        "user": SANDBOX_USER,
        "init": True,
        "labels": {
            LABEL_NAME: name,
            LABEL_LEVEL: level_name,
            LABEL_SUDO: str(level.sudo).lower(),
            LABEL_NET: level.network,
            LABEL_ALLOW: json.dumps(level.allow),
        },
        "environment": {
            "KT_SANDBOX_NAME": name,
            "KT_SANDBOX_WORKDIR": WORKDIR,
            "KT_SANDBOX_WALL_S": str(level.limits.wall_s),
            "KT_SANDBOX_OUTPUT_BYTES": str(level.limits.output_bytes),
            **proxy_environment(level, name, egress_secret),
            SECRET_ENV: egress_secret,
            **(env or {}),
        },
        "nano_cpus": int(level.limits.cpus * 1_000_000_000),
        "mem_limit": level.limits.memory,
        "memswap_limit": level.limits.memory,
        "pids_limit": level.limits.pids,
        "mounts": [
            {
                "Type": "bind",
                "Source": m.source,
                "Target": m.target,
                "ReadOnly": m.read_only,
            }
            for m in mounts
        ],
    }
    if not level.sudo:
        options["cap_drop"] = ["ALL"]
        options["security_opt"] = ["no-new-privileges:true"]
    if level.runtime:
        options["runtime"] = level.runtime
    if level.read_only:
        options["read_only"] = True
        options["tmpfs"] = {
            "/tmp": "size=64m",
            WORKDIR: "size=256m,uid=1000",
            "/run": "size=8m",
        }
    match level.network:
        case "none":
            options["network_mode"] = "none"
        case "allowlist":
            options["network"] = network_name(name)
    if publish is not None:
        options["ports"] = {f"{MCP_PORT}/tcp": publish}
    return options
