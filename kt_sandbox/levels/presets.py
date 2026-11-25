"""The named levels (``open``, ``standard``, ``strict``) and overrides on top of them."""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from kt_sandbox.errors import LevelError
from kt_sandbox.levels.models import Level

DEFAULT_ALLOW = [
    "pypi.org",
    "files.pythonhosted.org",
    "github.com",
    "raw.githubusercontent.com",
]

DEFAULT_LEVEL = "standard"

LEVELS: dict[str, dict[str, Any]] = {
    "open": {
        "network": "open",
        "sudo": True,
        "limits": {"cpus": 2.0, "memory": "2g", "pids": 512, "wall_s": 300},
    },
    "standard": {
        "network": "allowlist",
        "allow": DEFAULT_ALLOW,
        "limits": {"cpus": 1.0, "memory": "1g", "pids": 256, "wall_s": 60},
    },
    "strict": {
        "network": "none",
        "limits": {"cpus": 0.5, "memory": "256m", "pids": 64, "wall_s": 15},
    },
}


def build_level(name: str, overrides: Mapping[str, Any] | None = None) -> Level:
    """Return level ``name`` with ``overrides`` applied.

    ``limits`` merge field by field; every other field replaces the preset's.
    Moving a level off ``allowlist`` drops its host list.
    """
    if name not in LEVELS:
        raise LevelError(f"unknown level {name!r}; use one of {sorted(LEVELS)}")
    data = dict(overrides or {})
    base = deepcopy(LEVELS[name])
    limits = {**base.pop("limits", {}), **data.pop("limits", {})}
    merged = {**base, **data, "limits": limits}
    if "network" in data and data["network"] != "allowlist" and "allow" not in data:
        merged.pop("allow", None)
    try:
        return Level.model_validate(merged)
    except ValidationError as exc:
        raise LevelError(str(exc)) from exc
