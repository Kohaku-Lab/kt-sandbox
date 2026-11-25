"""Server settings read from the environment the manager sets for a sandbox."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_WORKDIR = "/work"
DEFAULT_WALL_S = 30
DEFAULT_OUTPUT_BYTES = 12 * 1024


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


@dataclass(frozen=True)
class ServerSettings:
    """Where tools work, the sandbox's name and the ceilings on one call."""

    workdir: Path
    wall_s: int = DEFAULT_WALL_S
    output_bytes: int = DEFAULT_OUTPUT_BYTES
    name: str = ""

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ServerSettings":
        """Read ``KT_SANDBOX_WORKDIR``, ``_WALL_S``, ``_OUTPUT_BYTES`` and ``_NAME``.

        The work folder defaults to ``/work`` when it exists, else the current folder.
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
        )
