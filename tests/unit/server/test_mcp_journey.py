"""The sandbox MCP server end to end: a real server process, a real MCP client, both transports."""

import base64
import os
import socket
import subprocess
import sys
import struct
import time
import zlib

import httpx
import pytest
from kohakuterrarium.builtins.tools.bash.bash import BashTool
from kohakuterrarium.builtins.tools.files.glob import GlobTool
from kohakuterrarium.builtins.tools.files.grep import GrepTool
from kohakuterrarium.builtins.tools.files.multi_edit import MultiEditTool
from kohakuterrarium.builtins.tools.files.read import ReadTool
from kohakuterrarium.builtins.tools.files.tree import TreeTool
from kohakuterrarium.builtins.tools.files.write import WriteTool
from kohakuterrarium.core.registry import Registry
from kohakuterrarium.llm.tools.build import build_tool_schemas
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

TOKEN = "s3cret-token"


def png_bytes() -> bytes:
    """A valid 1x1 PNG."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixel = zlib.compress(b"\x00\xff\x00\x00")
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", pixel)
        + chunk(b"IEND", b"")
    )


def text_of(result) -> str:
    return "\n".join(part.text for part in result.content if part.type == "text")


def server_env(workdir, **extra) -> dict[str, str]:
    env = {
        **os.environ,
        "KT_SANDBOX_WORKDIR": str(workdir),
        "KT_SANDBOX_WALL_S": "3",
        "KT_SANDBOX_OUTPUT_BYTES": "2000",
        "KT_SANDBOX_NAME": "lab",
    }
    env.pop("KT_SANDBOX_MCP_TOKEN", None)
    return {**env, **extra}


def kt_schemas() -> dict[str, tuple[str, dict]]:
    """What KohakuTerrarium itself sends a model for its seven local tools."""
    registry = Registry()
    for tool_class in (
        BashTool,
        ReadTool,
        WriteTool,
        MultiEditTool,
        GlobTool,
        GrepTool,
        TreeTool,
    ):
        registry.register_tool(tool_class())
    return {
        schema.name: (schema.description, schema.parameters)
        for schema in build_tool_schemas(registry)
    }


async def journey(session: ClientSession, workdir) -> None:
    """Every tool, success and failure, through one MCP session."""
    init = await session.initialize()
    assert init.instructions.startswith("You work inside the sandbox lab:")
    assert "`sandbox:lab/<path>`" in init.instructions

    tools = (await session.list_tools()).tools
    assert {t.name: (t.description, t.inputSchema) for t in tools} == kt_schemas()
    assert len(tools) == 7

    async def call(tool: str, **arguments):
        return await session.call_tool(tool, arguments)

    # bash: exit code and both streams; the time limit holds; background jobs do not hang.
    failed = await call("bash", command="echo hi; echo oops >&2; exit 4")
    assert failed.isError
    assert [part.text for part in failed.content] == [
        "Command exited with code 4",
        "hi\noops\n",
    ]
    assert text_of(await call("bash", command="echo ok")) == "ok\n"

    started = time.monotonic()
    slow = await call("bash", command="exec sleep 30", timeout=100)
    assert slow.isError and text_of(slow) == "Command timed out after 3s"
    assert time.monotonic() - started < 10, "a request cannot lengthen the limit"
    short = await call("bash", command="exec sleep 30", timeout=1)
    assert text_of(short) == "Command timed out after 1s"

    started = time.monotonic()
    detached = await call("bash", command="(sleep 5; echo late) & echo done")
    assert text_of(detached) == "done\n" and time.monotonic() - started < 3

    loud = text_of(await call("bash", command="yes abcdefghij | head -c 200000"))
    assert "bytes omitted" in loud and len(loud.encode()) < 2100

    # write then read: a new file needs no read first.
    wrote = await call("write", path="notes/a.txt", content="héllo\nworld\n")
    assert not wrote.isError and text_of(wrote).startswith("Created ")
    assert (workdir / "notes" / "a.txt").read_text(encoding="utf-8") == "héllo\nworld\n"
    assert (
        text_of(await call("read", path="notes/a.txt")) == "     1→héllo\n     2→world"
    )

    # read-before-write: a file changed outside the tools must be read again.
    await call("bash", command="echo from-bash > notes/b.txt")
    refused = await call("write", path="notes/b.txt", content="replaced\n")
    assert refused.isError and "has not been read yet" in text_of(refused)
    await call("read", path="notes/b.txt")
    assert not (await call("write", path="notes/b.txt", content="replaced\n")).isError
    await call("bash", command="echo changed-again > notes/b.txt")
    stale = await call(
        "multi_edit", path="notes/b.txt", edits=[{"old": "changed", "new": "edited"}]
    )
    assert (
        stale.isError
        and (workdir / "notes" / "b.txt").read_text(encoding="utf-8")
        == "changed-again\n"
    )

    await call("read", path="notes/b.txt")
    edited = await call(
        "multi_edit",
        path="notes/b.txt",
        edits=[
            {"old": "changed", "new": "edited"},
            {"old": "again", "new": "twice"},
        ],
    )
    assert not edited.isError and "applied: 2" in text_of(edited)
    assert (workdir / "notes" / "b.txt").read_text(encoding="utf-8") == "edited-twice\n"

    assert sorted(text_of(await call("glob", pattern="**/*.txt")).split()) == [
        "notes/a.txt",
        "notes/b.txt",
    ]
    found = text_of(await call("grep", pattern="wor+ld"))
    assert "notes/a.txt" in found and "2: world" in found
    tree = text_of(await call("tree"))
    assert "notes/" in tree and "a.txt" in tree and "b.txt" in tree

    (workdir / "chart.png").write_bytes(png_bytes())
    image = await call("read", path="chart.png")
    assert [part.type for part in image.content] == ["text", "image"]
    assert image.content[1].mimeType == "image/png"
    assert base64.b64decode(image.content[1].data) == png_bytes()

    (workdir / "big.txt").write_text("line\n" * 5000, encoding="utf-8")
    big = text_of(await call("read", path="big.txt"))
    assert "bytes omitted" in big and len(big.encode()) < 2100

    missing = await call("read", path="nope.txt")
    assert missing.isError and text_of(missing) == "File not found: nope.txt"


async def test_stdio_journey(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "kt_sandbox.server"],
        env=server_env(workdir),
    )
    errors = tmp_path / "server-stderr.txt"
    with errors.open("w", encoding="utf-8") as errlog:
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                await journey(session, workdir)
    assert "Traceback" not in errors.read_text(encoding="utf-8")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_port(port: int, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(
                f"server exited early: {process.stderr.read().decode()}"
            )
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise AssertionError("server did not start listening")


@pytest.fixture
def http_server(tmp_path):
    port = free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "kt_sandbox.server",
            "--transport",
            "http",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=server_env(tmp_path, KT_SANDBOX_MCP_TOKEN=TOKEN),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        wait_for_port(port, process)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        process.terminate()
        process.wait(timeout=10)


async def test_http_journey_with_the_bearer_token(http_server, tmp_path):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with httpx.AsyncClient(headers=headers) as http_client:
        async with streamable_http_client(http_server, http_client=http_client) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                await journey(session, tmp_path)


async def test_http_refuses_a_missing_or_wrong_token(http_server):
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    async with httpx.AsyncClient() as client:
        missing = await client.post(http_server, json=body)
        wrong = await client.post(
            http_server, json=body, headers={"Authorization": "Bearer nope"}
        )
    assert missing.status_code == wrong.status_code == 401
    assert "Authorization: Bearer" in missing.text
