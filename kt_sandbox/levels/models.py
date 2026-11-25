"""The :class:`Level` model: network, resource limits, user and runtime of one sandbox."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NetworkMode = Literal["none", "allowlist", "open"]


class Limits(BaseModel):
    """Resource ceilings of a sandbox, and of one command run in it."""

    model_config = ConfigDict(extra="forbid")

    cpus: float = Field(1.0, gt=0)
    memory: str = "512m"
    pids: int = Field(256, ge=1)
    wall_s: int = Field(30, ge=1)
    output_bytes: int = Field(12 * 1024, ge=1)


class Level(BaseModel):
    """What a sandbox may do; applied as container settings when it is opened.

    ``network`` is ``none`` (no interface), ``allowlist`` (only the hosts in
    ``allow``, through the egress proxy) or ``open``. Every sandbox runs as the
    ``sandbox`` user. With ``sudo`` it can become root (to install packages);
    without it the sandbox drops every Linux capability and cannot gain
    privileges. ``runtime`` names a container runtime installed in the Docker engine;
    empty means the engine default.
    """

    model_config = ConfigDict(extra="forbid")

    network: NetworkMode = "none"
    allow: list[str] = Field(default_factory=list)
    sudo: bool = False
    read_only: bool = False
    runtime: str = ""
    limits: Limits = Field(default_factory=Limits)

    @model_validator(mode="after")
    def _network_matches_allow(self) -> "Level":
        if self.network == "allowlist" and not self.allow:
            raise ValueError("network 'allowlist' needs at least one host in allow")
        if self.network != "allowlist" and self.allow:
            raise ValueError("allow is only used with network 'allowlist'")
        return self
