"""Fetching a file's bytes from a sandbox, over HTTP and through ``docker exec``."""

import pytest

from kt_sandbox.kt_plugin.errors import SandboxFileError
from kt_sandbox.kt_plugin.fetch import fetch
from kt_sandbox.kt_plugin.registry import DockerSource, HttpSource

MAX = 1024


def _http(server, base="/mcp", token=None) -> HttpSource:
    token = token or server.token
    return HttpSource(
        server="lab",
        url=f"{server.url}{base}",
        headers={"Authorization": f"Bearer {token}"},
    )


async def test_http_relative_and_absolute(file_server):
    (file_server.root / "work" / "a.txt").write_bytes(b"hello")
    (file_server.root / "etc").mkdir(exist_ok=True)
    (file_server.root / "etc" / "b.txt").write_bytes(b"\x00\x01")
    assert await fetch(_http(file_server), "a.txt", MAX) == b"hello"
    assert await fetch(_http(file_server), "/etc/b.txt", MAX) == b"\x00\x01"


async def test_http_wrong_token(file_server):
    with pytest.raises(SandboxFileError) as info:
        await fetch(_http(file_server, token="nope"), "a.txt", MAX)
    message = str(info.value)
    assert "rejected the token" in message
    assert "MCP server lab" in message
    assert "nope" not in message


async def test_http_missing_file(file_server):
    with pytest.raises(SandboxFileError, match="no file missing.txt in lab"):
        await fetch(_http(file_server), "missing.txt", MAX)


async def test_http_old_server_without_route(file_server):
    with pytest.raises(SandboxFileError, match="kt-sandbox upgrade") as info:
        await fetch(_http(file_server, base="/old/mcp"), "a.txt", MAX)
    assert "has no file route" in str(info.value)


async def test_http_too_large(file_server):
    (file_server.root / "work" / "big.bin").write_bytes(b"x" * (MAX + 1))
    with pytest.raises(SandboxFileError, match="over 1024"):
        await fetch(_http(file_server), "big.bin", MAX)


async def test_http_body_over_the_limit_is_refused_even_if_the_server_sends_it(
    file_server,
):
    (file_server.root / "work" / "huge.bin").write_bytes(b"x" * (MAX * 8))
    with pytest.raises(SandboxFileError, match="over 1024"):
        await fetch(_http(file_server, base="/greedy/mcp"), "huge.bin", MAX)
    (file_server.root / "work" / "fits.bin").write_bytes(b"y" * MAX)
    assert await fetch(_http(file_server, base="/greedy/mcp"), "fits.bin", MAX) == (
        b"y" * MAX
    )


async def test_http_not_a_regular_file(file_server):
    (file_server.root / "work" / "folder").mkdir(exist_ok=True)
    with pytest.raises(SandboxFileError, match="not a regular file"):
        await fetch(_http(file_server), "folder", MAX)


async def test_http_bad_path(file_server):
    with pytest.raises(SandboxFileError, match="bad path"):
        await fetch(_http(file_server), "a/../b", MAX)


async def test_http_unreachable():
    source = HttpSource(
        server="lab",
        url="http://127.0.0.1:9/mcp",
        headers={"Authorization": "Bearer hidden"},
    )
    with pytest.raises(SandboxFileError, match="cannot reach http://127.0.0.1:9") as e:
        await fetch(source, "a.txt", MAX)
    assert "hidden" not in str(e.value)


def _docker(container="sandbox-lab", env=None) -> DockerSource:
    return DockerSource(
        server="lab", docker="docker", container=container, env=env or {}
    )


async def test_docker_success_passes_arguments_and_env(fake_docker, monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "ssh://from-shell")
    (fake_docker.root / "work" / "a.png").write_bytes(b"\x89PNG")
    assert await fetch(_docker(), "a.png", MAX) == b"\x89PNG"
    call = fake_docker.calls()[-1]
    assert call["argv"] == [
        "exec",
        "sandbox-lab",
        "kt-sandbox-file",
        "a.png",
        "--max-bytes",
        str(MAX),
    ]
    assert call["DOCKER_HOST"] == "ssh://from-shell"


async def test_docker_entry_env_overrides(fake_docker, monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "ssh://from-shell")
    (fake_docker.root / "work" / "a.txt").write_bytes(b"a")
    await fetch(_docker(env={"DOCKER_HOST": "ssh://entry"}), "a.txt", MAX)
    assert fake_docker.calls()[-1]["DOCKER_HOST"] == "ssh://entry"


async def test_docker_missing_file(fake_docker):
    with pytest.raises(SandboxFileError, match="no file nope.txt in lab"):
        await fetch(_docker(), "nope.txt", MAX)


async def test_docker_not_regular(fake_docker):
    (fake_docker.root / "work" / "d").mkdir()
    with pytest.raises(SandboxFileError, match="not a regular file"):
        await fetch(_docker(), "d", MAX)


async def test_docker_too_large(fake_docker):
    (fake_docker.root / "work" / "big").write_bytes(b"x" * (MAX + 1))
    with pytest.raises(SandboxFileError, match="over 1024"):
        await fetch(_docker(), "big", MAX)


async def test_docker_old_image(fake_docker):
    with pytest.raises(SandboxFileError, match="kt-sandbox upgrade") as info:
        await fetch(_docker(container="old"), "a.txt", MAX)
    assert "has no file route" in str(info.value)


async def test_docker_other_failure_shows_docker_message(fake_docker):
    with pytest.raises(SandboxFileError, match="No such container: gone"):
        await fetch(_docker(container="gone"), "a.txt", MAX)


async def test_docker_binary_missing(tmp_path):
    source = DockerSource(
        server="lab", docker=str(tmp_path / "no-docker"), container="c", env={}
    )
    with pytest.raises(SandboxFileError, match="cannot run"):
        await fetch(source, "a.txt", MAX)


async def test_upgrade_message_names_the_sandbox_when_the_names_follow_kt_sandbox(
    file_server, fake_docker
):
    http = HttpSource(
        server="sandbox-lab",
        url=f"{file_server.url}/old/mcp",
        headers={"Authorization": f"Bearer {file_server.token}"},
    )
    with pytest.raises(SandboxFileError, match="`kt-sandbox upgrade lab`"):
        await fetch(http, "a.txt", MAX)
    docker = DockerSource(
        server="x", docker="docker", container="kt-sandbox-bot", env={}
    )
    with pytest.raises(SandboxFileError, match="`kt-sandbox upgrade bot`"):
        await fetch(docker, "a.txt", MAX)
