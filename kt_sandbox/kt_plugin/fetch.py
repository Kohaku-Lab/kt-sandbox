"""Fetch one file's bytes from a sandbox: ``GET <url>/files`` over HTTP, or ``kt-sandbox-file`` through ``docker exec``."""

import asyncio
import json
import os

import httpx

from kt_sandbox.kt_plugin.errors import SandboxFileError, upgrade_message
from kt_sandbox.kt_plugin.registry import DockerSource, HttpSource

TIMEOUT = 60.0
CONNECT_TIMEOUT = 10.0
FILE_COMMAND = "kt-sandbox-file"
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_NOT_REGULAR = 4
EXIT_TOO_LARGE = 5
MISSING_COMMAND_EXITS = {126, 127}
ERROR_BODY_LIMIT = 64 * 1024


def sandbox_name(source: HttpSource | DockerSource) -> str | None:
    """The sandbox's name when the registry entry follows ``kt-sandbox mcp``'s naming."""
    if isinstance(source, DockerSource) and source.container.startswith("kt-sandbox-"):
        return source.container.removeprefix("kt-sandbox-")
    if source.server.startswith("sandbox-"):
        return source.server.removeprefix("sandbox-")
    return None


def _error_text(body: bytes) -> str | None:
    """The ``error`` string of a ``{"error": "..."}`` body, else None."""
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    error = data.get("error") if isinstance(data, dict) else None
    return error if isinstance(error, str) else None


async def _read_capped(response: httpx.Response, limit: int) -> bytes | None:
    """The body, or None as soon as it grows past ``limit`` bytes."""
    chunks = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


async def _fetch_http(source: HttpSource, path: str, max_bytes: int) -> bytes:
    url = source.files_url
    timeout = httpx.Timeout(TIMEOUT, connect=CONNECT_TIMEOUT)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "GET",
                url,
                params={"path": path, "max_bytes": str(max_bytes)},
                headers=source.headers,
            ) as response:
                status = response.status_code
                limit = max_bytes if status == 200 else ERROR_BODY_LIMIT
                body = await _read_capped(response, limit)
    except httpx.HTTPError as exc:
        reason = str(exc) or type(exc).__name__
        raise SandboxFileError(f"cannot reach {url}: {reason}") from None
    error = _error_text(body or b"") if status != 200 else None
    match status:
        case 200:
            if body is None:
                raise SandboxFileError(
                    f"{path} in {source.server} is over {max_bytes} bytes"
                )
            return body
        case 401 | 403:
            raise SandboxFileError(
                "the sandbox rejected the token: check the headers of MCP server "
                f"{source.server}"
            )
        case 404 if error is not None:
            raise SandboxFileError(f"no file {path} in {source.server}")
        case 404 | 405 | 406:
            raise SandboxFileError(upgrade_message(sandbox_name(source)))
        case _ if error is not None:
            raise SandboxFileError(f"{source.server}: {error}")
        case _:
            raise SandboxFileError(f"{source.server} answered HTTP {status} for {path}")


async def _fetch_docker(source: DockerSource, path: str, max_bytes: int) -> bytes:
    argv = [
        source.docker,
        "exec",
        source.container,
        FILE_COMMAND,
        path,
        "--max-bytes",
        str(max_bytes),
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **source.env},
        )
    except OSError as exc:
        raise SandboxFileError(f"cannot run {source.docker}: {exc}") from None
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), TIMEOUT)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise SandboxFileError(
            f"{source.server} did not send {path} within {TIMEOUT:.0f} s"
        ) from None
    message = stderr.decode("utf-8", "replace").strip()
    last = message.splitlines()[-1] if message else ""
    match process.returncode:
        case 0:
            return stdout
        case code if code == EXIT_NOT_FOUND:
            raise SandboxFileError(f"no file {path} in {source.server}")
        case code if code in (EXIT_NOT_REGULAR, EXIT_TOO_LARGE, EXIT_USAGE):
            raise SandboxFileError(f"{source.server}: {last}")
        case code if code in MISSING_COMMAND_EXITS or FILE_COMMAND in message:
            raise SandboxFileError(upgrade_message(sandbox_name(source)))
        case code:
            raise SandboxFileError(
                f"docker exec {source.container} failed (exit {code}): {last}"
            )


async def fetch(source: HttpSource | DockerSource, path: str, max_bytes: int) -> bytes:
    """The bytes of ``path`` in the sandbox; raise :class:`SandboxFileError` with what to do."""
    if isinstance(source, HttpSource):
        return await _fetch_http(source, path, max_bytes)
    return await _fetch_docker(source, path, max_bytes)
