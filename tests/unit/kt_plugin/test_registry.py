"""Finding a sandbox's file source in KohakuTerrarium's global MCP registry."""

import pytest

from kt_sandbox.kt_plugin.errors import SandboxFileError
from kt_sandbox.kt_plugin.registry import DockerSource, HttpSource, find_source


@pytest.mark.parametrize("transport", ["streamable_http", "http", "sse"])
def test_http_entry(registry, transport):
    registry(
        [
            {
                "name": "lab",
                "transport": transport,
                "url": "http://vps:18765/mcp/",
                "headers": {"Authorization": "Bearer abc"},
            }
        ]
    )
    source = find_source("lab")
    assert source == HttpSource(
        server="lab",
        url="http://vps:18765/mcp/",
        headers={"Authorization": "Bearer abc"},
    )
    assert source.files_url == "http://vps:18765/mcp/files"


def test_env_vars_expand_in_url_and_headers(registry, monkeypatch):
    monkeypatch.setenv("LAB_HOST", "vps")
    monkeypatch.setenv("LAB_TOKEN", "tok-123")
    registry(
        [
            {
                "name": "lab",
                "transport": "streamable_http",
                "url": "http://${LAB_HOST}:${LAB_PORT:18765}/mcp",
                "headers": {"Authorization": "Bearer ${LAB_TOKEN}"},
            }
        ]
    )
    source = find_source("lab")
    assert source.url == "http://vps:18765/mcp"
    assert source.headers == {"Authorization": "Bearer tok-123"}


def test_unset_env_var_names_the_variable(registry, monkeypatch):
    monkeypatch.delenv("LAB_TOKEN", raising=False)
    registry(
        [
            {
                "name": "lab",
                "transport": "http",
                "url": "http://vps/mcp",
                "headers": {"Authorization": "Bearer ${LAB_TOKEN}"},
            }
        ]
    )
    with pytest.raises(SandboxFileError, match="LAB_TOKEN") as info:
        find_source("lab")
    assert "headers" in str(info.value)


def test_stdio_docker_exec_entry(registry, monkeypatch):
    monkeypatch.setenv("SB", "sandbox-lab")
    registry(
        [
            {
                "name": "lab",
                "transport": "stdio",
                "command": "docker",
                "args": ["exec", "-i", "-e", "X=1", "${SB}", "kt-sandbox-mcp"],
                "env": {"DOCKER_HOST": "ssh://vps"},
            }
        ]
    )
    source = find_source("lab")
    assert source == DockerSource(
        server="lab",
        docker="docker",
        container="sandbox-lab",
        env={"DOCKER_HOST": "ssh://vps"},
    )


def test_stdio_without_transport_defaults_to_stdio(registry):
    registry(
        [
            {
                "name": "lab",
                "command": "/usr/local/bin/docker",
                "args": ["exec", "--interactive", "c1", "kt-sandbox-mcp", "--x"],
            }
        ]
    )
    source = find_source("lab")
    assert isinstance(source, DockerSource)
    assert source.docker == "/usr/local/bin/docker"
    assert source.container == "c1"


@pytest.mark.parametrize(
    "entry",
    [
        {"name": "lab", "transport": "stdio", "command": "npx", "args": ["x"]},
        {
            "name": "lab",
            "transport": "stdio",
            "command": "docker",
            "args": ["run", "-i", "img"],
        },
        {
            "name": "lab",
            "transport": "stdio",
            "command": "docker",
            "args": ["exec", "-i", "c1", "python", "server.py"],
        },
    ],
)
def test_other_stdio_commands_are_refused(registry, entry):
    registry([entry])
    with pytest.raises(SandboxFileError, match="docker exec"):
        find_source("lab")


def test_unknown_server(registry):
    registry([{"name": "other", "transport": "http", "url": "http://x/mcp"}])
    with pytest.raises(SandboxFileError, match="no MCP server named 'lab'"):
        find_source("lab")


def test_missing_registry_file(registry):
    with pytest.raises(SandboxFileError, match="no MCP server named 'lab'"):
        find_source("lab")


def test_http_entry_without_url(registry):
    registry([{"name": "lab", "transport": "http"}])
    with pytest.raises(SandboxFileError, match="url"):
        find_source("lab")


def test_unknown_transport(registry):
    registry([{"name": "lab", "transport": "carrier-pigeon"}])
    with pytest.raises(SandboxFileError, match="carrier-pigeon"):
        find_source("lab")
