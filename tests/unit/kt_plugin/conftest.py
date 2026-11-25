"""Fixtures for the ``sandbox.files`` plugin: a real file-route server, a registry and a fake ``docker``."""

import json
import os
import socket
import stat
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import pytest
import uvicorn
import yaml
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

TOKEN = "s3cret-token-value"


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _file_app(root: Path) -> Starlette:
    """The ``GET <entry url>/files`` contract, served from ``root`` (``/work`` is ``root/work``)."""

    async def files(request: Request) -> Response:
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return _error(401, "missing or wrong bearer token")
        raw = request.query_params.get("path", "")
        max_bytes = int(request.query_params.get("max_bytes", "0") or 0)
        if not raw or ".." in raw.split("/"):
            return _error(400, f"bad path {raw!r}")
        target = root / raw.lstrip("/") if raw.startswith("/") else root / "work" / raw
        if not target.exists():
            return _error(404, f"no such file: {raw}")
        if not target.is_file():
            return _error(422, f"{raw} is not a regular file")
        data = target.read_bytes()
        if max_bytes and len(data) > max_bytes:
            return _error(413, f"{raw} is {len(data)} bytes, over {max_bytes}")
        return Response(
            data,
            media_type="application/octet-stream",
            headers={
                "X-KT-Sandbox-Size": str(len(data)),
                "X-KT-Sandbox-Mtime": str(int(target.stat().st_mtime)),
            },
        )

    async def greedy(request: Request) -> Response:
        """A server that ignores ``max_bytes`` and sends the whole file."""
        raw = request.query_params.get("path", "")
        return Response((root / "work" / raw).read_bytes())

    async def mcp(request: Request) -> Response:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32600}},
            status_code=406,
        )

    return Starlette(
        routes=[
            Route("/mcp/files", files),
            Route("/greedy/mcp/files", greedy),
            Route("/mcp", mcp, methods=["GET", "POST"]),
            Route("/old/mcp", mcp, methods=["GET", "POST"]),
        ]
    )


@dataclass
class FileServer:
    """A running file-route server: ``url`` is the base, ``root`` holds the sandbox's files."""

    url: str
    root: Path
    token: str = TOKEN


@pytest.fixture(scope="session")
def file_server(tmp_path_factory) -> FileServer:
    root = tmp_path_factory.mktemp("sandbox-root")
    (root / "work").mkdir()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(
        uvicorn.Config(_file_app(root), host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    yield FileServer(url=f"http://127.0.0.1:{port}", root=root)
    server.should_exit = True
    thread.join(timeout=5)


FAKE_DOCKER = r"""
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
log = os.environ.get("FAKE_DOCKER_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"argv": args, "DOCKER_HOST": os.environ.get("DOCKER_HOST")}) + "\n")
if len(args) < 3 or args[0] != "exec":
    sys.stderr.write("fake docker: unsupported call\n")
    sys.exit(1)
container, command, rest = args[1], args[2], args[3:]
if container in ("old", "kt-sandbox-bot") or command != "kt-sandbox-file":
    sys.stderr.write(
        'OCI runtime exec failed: exec failed: unable to start container process: '
        'exec: "kt-sandbox-file": executable file not found in $PATH: unknown\n'
    )
    sys.exit(127)
if container == "gone":
    sys.stderr.write("Error response from daemon: No such container: gone\n")
    sys.exit(1)
if len(rest) != 3 or rest[1] != "--max-bytes":
    sys.stderr.write("usage: kt-sandbox-file PATH --max-bytes N\n")
    sys.exit(2)
raw, max_bytes = rest[0], int(rest[2])
root = Path(os.environ["FAKE_SANDBOX_ROOT"])
target = root / raw.lstrip("/") if raw.startswith("/") else root / "work" / raw
if not target.exists():
    sys.stderr.write(f"no such file: {raw}\n")
    sys.exit(3)
if not target.is_file():
    sys.stderr.write(f"{raw} is not a regular file\n")
    sys.exit(4)
data = target.read_bytes()
if len(data) > max_bytes:
    sys.stderr.write(f"{raw} is {len(data)} bytes, over {max_bytes}\n")
    sys.exit(5)
sys.stdout.buffer.write(data)
"""


@dataclass
class FakeDocker:
    """A ``docker`` on PATH answering ``exec <container> kt-sandbox-file``; ``log`` records each call."""

    root: Path
    log: Path

    def calls(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text("utf-8").splitlines()]


@pytest.fixture
def fake_docker(tmp_path, monkeypatch) -> FakeDocker:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "docker"
    script.write_text(f"#!{sys.executable}\n{FAKE_DOCKER}", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    root = tmp_path / "container"
    (root / "work").mkdir(parents=True)
    log = tmp_path / "docker-log.jsonl"
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_SANDBOX_ROOT", str(root))
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    return FakeDocker(root=root, log=log)


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Write ``mcp_servers.yaml`` into a fresh ``KT_CONFIG_DIR``; call it with the entry list."""
    config = tmp_path / "kt-config"
    config.mkdir()
    monkeypatch.setenv("KT_CONFIG_DIR", str(config))

    def write(entries: list[dict]) -> Path:
        path = config / "mcp_servers.yaml"
        path.write_text(yaml.safe_dump(entries), encoding="utf-8")
        return path

    return write
