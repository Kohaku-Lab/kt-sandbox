"""The allowlist level's plumbing: an internal-only network and the egress proxy container.

Sandboxes at the allowlist level sit on a network with no gateway; the egress
proxy is attached to that network and to the default one, so it is their only
way out. The proxy learns each sandbox's credential and hosts from a policy
file this module keeps current.
"""

import io
import json
import secrets
import tarfile
import time
from pathlib import PurePosixPath

import docker
from docker.errors import APIError, NotFound
from docker.models.containers import Container

from kt_sandbox.errors import ManagerError
from kt_sandbox.levels.models import Level
from kt_sandbox.manager.docker import images
from kt_sandbox.manager.options import (
    EGRESS_NAME,
    EGRESS_POLICY_DIR,
    EGRESS_POLICY_FILE,
    EGRESS_PORT,
    LABEL_ALLOW,
    LABEL_EGRESS,
    LABEL_NAME,
    LABEL_NET,
    SANDBOX_USER,
    SECRET_ENV,
    network_name,
)

READY_TIMEOUT_S = 20
PROBE = (
    "import socket,sys; socket.create_connection(('127.0.0.1', %d), 2).close()"
    % EGRESS_PORT
)


def new_secret() -> str:
    """Return a fresh credential for one sandbox at the egress proxy."""
    return secrets.token_urlsafe(18)


def policy_entries(containers: list[Container]) -> list[dict]:
    """Build the proxy's table from the sandbox containers that use the allowlist."""
    entries = []
    for container in containers:
        labels = container.labels
        if labels.get(LABEL_NET) != "allowlist":
            continue
        env = dict(
            item.split("=", 1)
            for item in container.attrs["Config"].get("Env") or []
            if "=" in item
        )
        secret = env.get(SECRET_ENV, "")
        if secret:
            entries.append(
                {
                    "name": labels[LABEL_NAME],
                    "secret": secret,
                    "allow": json.loads(labels.get(LABEL_ALLOW, "[]")),
                }
            )
    return entries


def _tar_of(name: str, content: bytes) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(content)
        info.mode = 0o644
        info.mtime = int(time.time())
        archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def ensure_sandbox_network(
    client: docker.DockerClient, name: str, proxy: Container
) -> None:
    """Create sandbox ``name``'s own internal network and attach the egress proxy to it.

    One network per sandbox keeps sandboxes from reaching each other: the proxy is
    the only other member.
    """
    wanted = network_name(name)
    try:
        net = client.networks.get(wanted)
    except NotFound:
        net = client.networks.create(wanted, driver="bridge", internal=True)
    net.reload()
    if proxy.id not in {c.id for c in net.containers}:
        net.connect(proxy)


def remove_sandbox_network(client: docker.DockerClient, name: str) -> None:
    """Detach the proxy from sandbox ``name``'s network and delete the network."""
    try:
        net = client.networks.get(network_name(name))
    except NotFound:
        return
    for member in list(net.containers):
        if member.name == EGRESS_NAME:
            net.disconnect(member, force=True)
    try:
        net.remove()
    except APIError:
        pass


def _wait_ready(container: Container) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        container.reload()
        if container.status == "exited":
            raise ManagerError(
                "the egress proxy stopped right after starting; see `docker logs "
                f"{EGRESS_NAME}`."
            )
        if container.status == "running":
            code, _ = container.exec_run(["python", "-c", PROBE])
            if code == 0:
                return
        time.sleep(0.3)
    raise ManagerError(
        f"the egress proxy did not start listening; see `docker logs {EGRESS_NAME}`."
    )


def ensure_egress(client: docker.DockerClient, image: str) -> Container:
    """Make sure the internal network and a running egress proxy exist; return the proxy."""
    try:
        container = client.containers.get(EGRESS_NAME)
    except NotFound:
        images.ensure(client, image)
        try:
            container = client.containers.create(
                image,
                name=EGRESS_NAME,
                command=["kt-sandbox", "proxy"],
                user=SANDBOX_USER,
                init=True,
                labels={LABEL_EGRESS: "1"},
                tmpfs={"/tmp": "size=16m"},
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                mem_limit="256m",
                pids_limit=128,
                restart_policy={"Name": "unless-stopped"},
            )
        except APIError as exc:
            raise ManagerError(
                f"Docker could not create the egress proxy: {exc.explanation or exc}"
            ) from exc
    if container.status != "running":
        container.start()
        _wait_ready(container)
    return container


def sync_policy(client: docker.DockerClient) -> None:
    """Write every allowlist sandbox's credential and hosts into the running egress proxy."""
    try:
        proxy = client.containers.get(EGRESS_NAME)
    except NotFound:
        return
    if proxy.status != "running":
        return
    sandboxes = client.containers.list(all=True, filters={"label": LABEL_NAME})
    payload = json.dumps({"sandboxes": policy_entries(sandboxes)}).encode("utf-8")
    try:
        proxy.put_archive(
            str(PurePosixPath(EGRESS_POLICY_DIR).parent),
            _tar_of(
                f"{PurePosixPath(EGRESS_POLICY_DIR).name}/{EGRESS_POLICY_FILE}", payload
            ),
        )
    except APIError as exc:
        raise ManagerError(
            f"could not give the egress proxy its policy: {exc.explanation or exc}"
        ) from exc


def prune_egress(client: docker.DockerClient) -> bool:
    """Remove the egress proxy when no allowlist sandbox is left; return whether it was removed."""
    sandboxes = client.containers.list(
        all=True, filters={"label": f"{LABEL_NET}=allowlist"}
    )
    if sandboxes:
        return False
    try:
        client.containers.get(EGRESS_NAME).remove(force=True)
    except NotFound:
        return False
    return True


def prepare(client: docker.DockerClient, level: Level, image: str, name: str) -> str:
    """Prepare the network sandbox ``name`` needs; return its egress credential (or "")."""
    if level.network != "allowlist":
        return ""
    proxy = ensure_egress(client, image)
    ensure_sandbox_network(client, name, proxy)
    return new_secret()
