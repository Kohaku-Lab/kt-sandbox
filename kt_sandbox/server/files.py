"""Hand one sandbox file to a caller outside: the rule, the ``/mcp/files`` route and ``kt-sandbox-file``.

The rule: a relative path is under the work folder, an absolute one is used as
given; the last component must be a regular file, never a symbolic link, a
folder or a special file; a file over the byte limit is refused before any byte
is sent.
"""

import argparse
import errno
import logging
import os
import stat
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from kt_sandbox.errors import BadReference, NotAFile, NotFound, SandboxError, TooLarge
from kt_sandbox.server.settings import ServerSettings

LOG = logging.getLogger("kt_sandbox.server.files")
ROUTE_PATH = "/mcp/files"
MAX_BYTES = 64 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
COMMAND = "kt-sandbox-file"

EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_NOT_A_FILE = 4
EXIT_TOO_LARGE = 5
EXIT_UNREADABLE = 6


class Unreadable(SandboxError, PermissionError):
    """The server's user may not read the file."""


def limit_of(requested: int | None) -> int:
    """Return the byte limit for one read: ``requested`` clamped to :data:`MAX_BYTES`."""
    if requested is None:
        return MAX_BYTES
    if requested < 1:
        raise BadReference(f"max_bytes must be at least 1, got {requested}")
    return min(requested, MAX_BYTES)


def too_large(path: Path, size: int, limit: int) -> TooLarge:
    """The error for a file over ``limit``."""
    return TooLarge(
        f"{path} is {size} bytes, over the {limit}-byte limit; make a smaller "
        "file (compress, resize or split it) and send that"
    )


def target(path: str, workdir: Path) -> Path:
    """Return the file ``path`` names: relative is under ``workdir``, absolute as given."""
    if not path or not path.strip():
        raise BadReference("the path is empty; name a file, for example out/chart.png")
    return Path(path) if path.startswith("/") else workdir / path


def _refuse(found: Path, info: os.stat_result) -> None:
    mode = info.st_mode
    if stat.S_ISDIR(mode):
        raise NotAFile(f"{found} is a folder; name a file in it")
    if stat.S_ISLNK(mode):
        raise NotAFile(
            f"{found} is a symbolic link to {os.readlink(found)}; name a regular "
            "file instead"
        )
    if not stat.S_ISREG(mode):
        raise NotAFile(
            f"{found} is a special file (a pipe, socket or device); only regular "
            "files can be read"
        )


class OpenedFile:
    """One regular file opened for sending: its path, size, mtime and byte limit."""

    def __init__(self, path: Path, fd: int, info: os.stat_result, limit: int):
        self.path = path
        self.size = info.st_size
        self.mtime = info.st_mtime
        self.limit = limit
        self._handle = os.fdopen(fd, "rb", buffering=0)

    def chunks(self) -> Iterator[bytes]:
        """Yield the file's bytes, at most its size when opened; past ``limit`` raise TooLarge."""
        sent = 0
        try:
            while sent < self.size:
                chunk = self._handle.read(min(CHUNK_BYTES, self.size - sent))
                if not chunk:
                    return
                sent += len(chunk)
                if sent > self.limit:
                    raise too_large(self.path, self.size, self.limit)
                yield chunk
        finally:
            self.close()

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> "OpenedFile":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def open_file(path: str, workdir: Path, *, max_bytes: int | None = None) -> OpenedFile:
    """Open the file ``path`` names under the rule; blocking (can be to_thread).

    Every refusal is a :class:`~kt_sandbox.errors.SandboxError`: BadReference,
    NotFound, NotAFile, TooLarge or :class:`Unreadable`.
    """
    limit = limit_of(max_bytes)
    found = target(path, workdir)
    try:
        _refuse(found, os.lstat(found))
        fd = os.open(found, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except (FileNotFoundError, NotADirectoryError):
        raise NotFound(
            f"{found} does not exist; check the path (a relative path starts at "
            f"{workdir})"
        ) from None
    except PermissionError:
        raise Unreadable(f"{found} cannot be read by the sandbox user") from None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise NotAFile(f"{found} is a symbolic link; name a regular file") from None
        raise
    try:
        info = os.fstat(fd)
        _refuse(found, info)
        if info.st_size > limit:
            raise too_large(found, info.st_size, limit)
    except BaseException:
        os.close(fd)
        raise
    return OpenedFile(found, fd, info, limit)


def _status_of(exc: SandboxError) -> int:
    match exc:
        case BadReference():
            return 400
        case Unreadable():
            return 403
        case NotFound():
            return 404
        case TooLarge():
            return 413
        case NotAFile():
            return 422
    return 500


def _requested_limit(raw: str | None) -> int | None:
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError:
        raise BadReference(f"max_bytes must be a whole number, got {raw!r}") from None


def endpoint(settings: ServerSettings):
    """Return the ASGI endpoint of ``GET /mcp/files`` for a server working in ``settings.workdir``."""

    async def serve(request: Request) -> Response:
        path = request.query_params.get("path", "")
        try:
            limit = _requested_limit(request.query_params.get("max_bytes"))
            opened = await run_in_threadpool(
                open_file, path, settings.workdir, max_bytes=limit
            )
        except SandboxError as exc:
            status = _status_of(exc)
            LOG.info("GET %s path=%r status=%d", ROUTE_PATH, path, status)
            return JSONResponse({"error": str(exc)}, status_code=status)
        LOG.info("GET %s path=%r status=200 bytes=%d", ROUTE_PATH, path, opened.size)
        return StreamingResponse(
            opened.chunks(),
            media_type="application/octet-stream",
            headers={
                "Content-Length": str(opened.size),
                "X-KT-Sandbox-Size": str(opened.size),
                "X-KT-Sandbox-Mtime": repr(opened.mtime),
            },
            background=BackgroundTask(opened.close),
        )

    return serve


def _exit_code(exc: SandboxError) -> int:
    match exc:
        case BadReference():
            return EXIT_USAGE
        case Unreadable():
            return EXIT_UNREADABLE
        case NotFound():
            return EXIT_NOT_FOUND
        case TooLarge():
            return EXIT_TOO_LARGE
        case NotAFile():
            return EXIT_NOT_A_FILE
    return 1


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of ``kt-sandbox-file``."""
    parser = argparse.ArgumentParser(
        prog=COMMAND,
        description="Write one regular file of this sandbox to stdout.",
        epilog="Exit codes: 3 not found, 4 not a regular file, 5 too large, 2 usage.",
    )
    parser.add_argument("path", help="relative to the work folder, or absolute")
    parser.add_argument(
        "--max-bytes",
        type=int,
        help=f"refuse a larger file (default and ceiling {MAX_BYTES})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Write the file's bytes to stdout; on a refusal print why and return its exit code."""
    args = build_parser().parse_args(argv)
    try:
        settings = ServerSettings.from_env()
        with open_file(args.path, settings.workdir, max_bytes=args.max_bytes) as f:
            out = sys.stdout.buffer
            for chunk in f.chunks():
                out.write(chunk)
            out.flush()
    except SandboxError as exc:
        print(f"{COMMAND}: {exc}", file=sys.stderr)
        return _exit_code(exc)
    except ValueError as exc:
        print(f"{COMMAND}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except BrokenPipeError:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
