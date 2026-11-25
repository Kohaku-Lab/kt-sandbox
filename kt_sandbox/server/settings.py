"""Server settings read from the environment the manager sets for a sandbox."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_WORKDIR = "/work"
DEFAULT_WALL_S = 30
DEFAULT_OUTPUT_BYTES = 12 * 1024
NETWORK_MODES = ("none", "allowlist", "open")


def _whole_number(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name, "")
    if not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {raw!r}") from None
    if value < 1:
        raise ValueError(f"{name} must be at least 1, got {value}")
    return value


def _network(environ: Mapping[str, str]) -> str:
    raw = environ.get("KT_SANDBOX_NETWORK", "").strip()
    if raw and raw not in NETWORK_MODES:
        raise ValueError(
            f"KT_SANDBOX_NETWORK must be one of {', '.join(NETWORK_MODES)}, got {raw!r}"
        )
    return raw


def _sudo(environ: Mapping[str, str]) -> bool | None:
    raw = environ.get("KT_SANDBOX_SUDO", "").strip()
    if not raw:
        return None
    if raw not in ("0", "1"):
        raise ValueError(f"KT_SANDBOX_SUDO must be 0 or 1, got {raw!r}")
    return raw == "1"


def _hosts(environ: Mapping[str, str]) -> tuple[str, ...]:
    raw = environ.get("KT_SANDBOX_ALLOW", "")
    return tuple(host.strip() for host in raw.split(",") if host.strip())


@dataclass(frozen=True)
class ServerSettings:
    """Where tools work, the sandbox's name, its level's policy and the ceilings on one call.

    ``level``, ``network``, ``allow`` and ``sudo`` describe the level the
    sandbox was opened at; empty (``sudo`` None) means not known, as for a
    server started by hand.
    """

    workdir: Path
    wall_s: int = DEFAULT_WALL_S
    output_bytes: int = DEFAULT_OUTPUT_BYTES
    name: str = ""
    level: str = ""
    network: str = ""
    allow: tuple[str, ...] = ()
    sudo: bool | None = None

    @property
    def has_policy(self) -> bool:
        """Whether the manager told the server anything about the sandbox's level."""
        return bool(self.level or self.network) or self.sudo is not None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ServerSettings":
        """Read the ``KT_SANDBOX_*`` variables; a blank one means its default.

        ``WORKDIR``, ``WALL_S``, ``OUTPUT_BYTES`` and ``NAME`` set where and how
        long tools run; ``LEVEL``, ``NETWORK`` (none, allowlist, open), ``ALLOW``
        (comma-separated hosts) and ``SUDO`` (0 or 1) describe the level. The
        work folder defaults to ``/work`` when it exists, else the current folder.
        """
        env = os.environ if environ is None else environ
        configured = env.get("KT_SANDBOX_WORKDIR", "")
        if configured:
            workdir = Path(configured)
        elif Path(DEFAULT_WORKDIR).is_dir():
            workdir = Path(DEFAULT_WORKDIR)
        else:
            workdir = Path.cwd()
        return cls(
            workdir=workdir,
            wall_s=_whole_number(env, "KT_SANDBOX_WALL_S", DEFAULT_WALL_S),
            output_bytes=_whole_number(
                env, "KT_SANDBOX_OUTPUT_BYTES", DEFAULT_OUTPUT_BYTES
            ),
            name=env.get("KT_SANDBOX_NAME", "").strip(),
            level=env.get("KT_SANDBOX_LEVEL", "").strip(),
            network=_network(env),
            allow=_hosts(env),
            sudo=_sudo(env),
        )
