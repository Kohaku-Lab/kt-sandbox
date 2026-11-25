"""Connect to the Docker engine, with an error a person can act on."""

import docker
from docker.errors import DockerException

from kt_sandbox.errors import ManagerError


def connect() -> docker.DockerClient:
    """Return a client for the engine in the environment, or raise saying what to do."""
    try:
        client = docker.from_env()
        client.ping()
    except DockerException as exc:
        raise ManagerError(
            f"cannot reach Docker ({exc}). Start Docker, or point DOCKER_HOST at an engine."
        ) from exc
    return client
