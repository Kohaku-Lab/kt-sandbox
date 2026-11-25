"""Read one file out of a sandbox from a ``sandbox:<name or id>/<path>`` reference.

The file comes through Docker's archive API, so the sandbox may be stopped and
symbolic links along the path resolve inside the container, never on the host.
This module needs the ``docker`` package (the ``manager`` extra); importing it
without that package raises ImportError.
"""

import io
import posixpath
import re
import tarfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

import docker
from docker.errors import APIError, DockerException
from docker.errors import NotFound as DockerNotFound
from docker.models.containers import Container

from kt_sandbox.errors import (
    BadReference,
    ManagerError,
    NotAFile,
    NotFound,
    SandboxError,
    TooLarge,
)
from kt_sandbox.manager.docker.engine import connect
from kt_sandbox.manager.options import LABEL_NAME, WORKDIR

PREFIX = "sandbox:"
FORM = "sandbox:<name>/<path>, for example sandbox:lab/out/chart.png"
CHUNK_BYTES = 64 * 1024
# Room for the tar headers and padding around one file, plus one chunk of read-ahead.
TAR_OVERHEAD = 128 * 1024
_HANDLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

# Type bits of Go's os.FileMode, as Docker reports them in a path's stat.
MODE_DIR = 1 << 31
MODE_SYMLINK = 1 << 27
# Device, named pipe, socket, character device and irregular file.
MODE_SPECIAL = (1 << 26) | (1 << 25) | (1 << 24) | (1 << 21) | (1 << 19)


@dataclass(frozen=True)
class SandboxFile:
    """One file read from a sandbox: the sandbox's name, the absolute path, the file name and bytes."""

    sandbox: str
    path: str
    name: str
    data: bytes


class _Overflow(Exception):
    """The archive stream went past its byte budget."""


class ChunkStream(io.RawIOBase):
    """A readable stream over byte chunks that refuses to pull more than ``budget`` bytes."""

    def __init__(self, chunks: Iterable[bytes], budget: int):
        self._chunks: Iterator[bytes] = iter(chunks)
        self._pending = memoryview(b"")
        self.budget = budget
        self.pulled = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        while not self._pending:
            if self.pulled >= self.budget:
                raise _Overflow
            chunk = next(self._chunks, None)
            if chunk is None:
                return 0
            self.pulled += len(chunk)
            self._pending = memoryview(chunk)
        count = min(len(buffer), len(self._pending))
        buffer[:count] = self._pending[:count]
        self._pending = self._pending[count:]
        return count


def parse_ref(ref: str) -> tuple[str, str]:
    """Split ``sandbox:<name>/<path>`` into the sandbox and the path.

    ``sandbox:lab/out/chart.png`` gives ``("lab", "out/chart.png")``;
    ``sandbox:lab//etc/hosts`` gives the absolute path ``/etc/hosts``.
    """
    rest = ref[len(PREFIX) :] if ref.startswith(PREFIX) else None
    handle, _, path = (rest or "").partition("/")
    if rest is None or not _HANDLE.match(handle) or not path:
        raise BadReference(f"{ref!r} is not a sandbox file reference; use {FORM}")
    return handle, path


def container_path(path: str) -> str:
    """Return ``path`` inside the container; a relative path is under the work folder."""
    return path if path.startswith("/") else posixpath.join(WORKDIR, path)


def find_sandbox(client: docker.DockerClient, handle: str) -> Container:
    """Return the sandbox named ``handle``, or the sandbox container with that id, id prefix or name.

    Only containers kt-sandbox opened count; any other container is "no sandbox".
    """
    labelled = client.containers.list(
        all=True, filters={"label": f"{LABEL_NAME}={handle}"}
    )
    if labelled:
        return labelled[0]
    try:
        container = client.containers.get(handle)
    except (DockerNotFound, APIError):
        container = None
    if container is None or LABEL_NAME not in (container.labels or {}):
        raise NotFound(f"no sandbox named {handle!r}; see `kt-sandbox ls`")
    return container


def refuse_by_stat(
    stat: dict[str, Any] | None, path: str, sandbox: str, max_bytes: int
) -> None:
    """Refuse a folder, a link, a special file or an oversize file from Docker's stat alone."""
    if not stat:
        return
    mode = int(stat.get("mode", 0))
    if mode & MODE_DIR:
        raise NotAFile(f"{path} in sandbox {sandbox} is a folder; name a file in it")
    if mode & MODE_SYMLINK:
        raise NotAFile(
            f"{path} in sandbox {sandbox} is a symbolic link to "
            f"{stat.get('linkTarget') or '?'}; name a regular file instead"
        )
    if mode & MODE_SPECIAL:
        raise NotAFile(
            f"{path} in sandbox {sandbox} is not a regular file; only regular "
            "files can be read"
        )
    size = int(stat.get("size", 0))
    if size > max_bytes:
        raise too_large(path, sandbox, size, max_bytes)


def too_large(path: str, sandbox: str, size: int | None, max_bytes: int) -> TooLarge:
    """The error for a file over ``max_bytes``, saying what to do instead."""
    known = f"is {size} bytes, " if size is not None else "is "
    return TooLarge(
        f"{path} in sandbox {sandbox} {known}over the {max_bytes}-byte limit; "
        "make a smaller file (compress, resize or split it) and send that"
    )


def extract_one(
    chunks: Iterable[bytes], path: str, sandbox: str, max_bytes: int
) -> tuple[str, bytes]:
    """Return the name and bytes of the single regular file in a tar stream.

    Reading stops once the stream passes ``max_bytes`` plus room for the tar
    headers, so an oversize file is never read whole.
    """
    stream = ChunkStream(chunks, max_bytes + TAR_OVERHEAD)
    try:
        with tarfile.open(fileobj=io.BufferedReader(stream), mode="r|") as archive:
            member = archive.next()
            if member is None:
                raise NotFound(f"{path} in sandbox {sandbox} came back empty")
            if member.issym() or member.islnk():
                raise NotAFile(
                    f"{path} in sandbox {sandbox} is a link to {member.linkname}; "
                    "name a regular file instead"
                )
            if member.isdir():
                raise NotAFile(
                    f"{path} in sandbox {sandbox} is a folder; name a file in it"
                )
            if not member.isreg():
                raise NotAFile(
                    f"{path} in sandbox {sandbox} is not a regular file; only "
                    "regular files can be read"
                )
            if member.size > max_bytes:
                raise too_large(path, sandbox, member.size, max_bytes)
            handle = archive.extractfile(member)
            data = handle.read(max_bytes + 1) if handle else b""
    except _Overflow:
        raise too_large(path, sandbox, None, max_bytes) from None
    except tarfile.TarError as exc:
        raise ManagerError(f"Docker sent a broken archive for {path}: {exc}") from exc
    if len(data) > max_bytes:
        raise too_large(path, sandbox, None, max_bytes)
    return posixpath.basename(member.name.rstrip("/")), data


def read_from(client: docker.DockerClient, ref: str, *, max_bytes: int) -> SandboxFile:
    """Read the file ``ref`` names through ``client``; see :func:`read`."""
    handle, raw_path = parse_ref(ref)
    container = find_sandbox(client, handle)
    sandbox = container.labels.get(LABEL_NAME, handle)
    path = container_path(raw_path)
    try:
        chunks, stat = container.get_archive(path, chunk_size=CHUNK_BYTES)
    except DockerNotFound:
        raise NotFound(
            f"{path} does not exist in sandbox {sandbox}; check the path "
            f"(a relative path starts at {WORKDIR})"
        ) from None
    except APIError as exc:
        raise ManagerError(
            f"Docker could not read {path} from sandbox {sandbox}: "
            f"{exc.explanation or exc}"
        ) from exc
    try:
        refuse_by_stat(stat, path, sandbox, max_bytes)
        name, data = extract_one(chunks, path, sandbox, max_bytes)
    except DockerException as exc:
        raise ManagerError(
            f"the connection to Docker broke while reading {path}: {exc}"
        ) from exc
    finally:
        close = getattr(chunks, "close", None)
        if close is not None:
            close()
    return SandboxFile(sandbox=sandbox, path=path, name=name, data=data)


def read(ref: str, *, max_bytes: int) -> SandboxFile:
    """Read the file ``sandbox:<name or id>/<path>`` names, refusing more than ``max_bytes``.

    Blocking. Every failure is a :class:`~kt_sandbox.errors.SandboxError` whose
    message says what to do next.
    """
    client = connect()
    try:
        return read_from(client, ref, max_bytes=max_bytes)
    except SandboxError:
        raise
    except DockerException as exc:
        raise ManagerError(
            f"cannot reach Docker ({exc}). Start Docker, or point DOCKER_HOST at an engine."
        ) from exc
    finally:
        client.close()
