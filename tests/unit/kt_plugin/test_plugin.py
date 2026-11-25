"""The ``sandbox.files`` plugin: argument rewriting, blocking, prompt, cleanup and hook order."""

from pathlib import Path
from typing import Any

import pytest

from kohakuterrarium.builtins.plugins.sandbox.plugin import SandboxPlugin
from kohakuterrarium.builtins.tools.files.read import ReadTool
from kohakuterrarium.modules.plugin.base import PluginBlockError, PluginContext
from kohakuterrarium.modules.plugin.manager.manager import PluginManager
from kohakuterrarium.modules.tool.base import BaseTool, ToolContext, ToolResult

from kt_sandbox.kt_plugin.plugin import SandboxFilesPlugin


class SendTool(BaseTool):
    """A ``qq_send``-like tool: ``media`` is a file (or files) it reads."""

    path_arguments = {"media": "read", "attachments": "read", "out": "write"}

    @property
    def tool_name(self) -> str:
        return "send"

    @property
    def description(self) -> str:
        return "send a message"

    async def _execute(self, args: dict[str, Any], **kwargs: Any) -> ToolResult:
        return ToolResult(output="sent")


class PlainTool(SendTool):
    """A tool that declares no file arguments."""

    path_arguments = {}


def _ctx(workdir: Path) -> ToolContext:
    return ToolContext(agent_name="a", session=None, working_dir=workdir)


async def _loaded(workdir: Path, **options: Any) -> SandboxFilesPlugin:
    plugin = SandboxFilesPlugin(**options)
    await plugin.on_load(PluginContext(agent_name="a", working_dir=workdir))
    return plugin


@pytest.fixture
def lab(file_server, registry):
    """``lab`` is an HTTP sandbox with files; ``vm`` is a docker-exec one."""
    registry(
        [
            {
                "name": "lab",
                "transport": "streamable_http",
                "url": f"{file_server.url}/mcp",
                "headers": {"Authorization": "Bearer ${LAB_TOKEN}"},
            },
            {
                "name": "oldlab",
                "transport": "streamable_http",
                "url": f"{file_server.url}/old/mcp",
                "headers": {"Authorization": f"Bearer {file_server.token}"},
            },
            {
                "name": "vm",
                "transport": "stdio",
                "command": "docker",
                "args": ["exec", "-i", "sandbox-vm", "kt-sandbox-mcp"],
            },
        ]
    )
    work = file_server.root / "work"
    (work / "out").mkdir(exist_ok=True)
    (work / "out" / "plot.png").write_bytes(b"PNG-DATA")
    (work / "notes.txt").write_bytes(b"notes")
    (file_server.root / "etc").mkdir(exist_ok=True)
    (file_server.root / "etc" / "conf").write_bytes(b"conf")
    return file_server


@pytest.fixture(autouse=True)
def lab_token(monkeypatch, file_server):
    monkeypatch.setenv("LAB_TOKEN", file_server.token)


async def _call(plugin, tool, args, workdir):
    return await plugin.pre_tool_execute(
        args, tool_name=tool.tool_name, tool=tool, job_id="j1", context=_ctx(workdir)
    )


async def test_rewrites_declared_read_arguments_including_lists(lab, tmp_path):
    plugin = await _loaded(tmp_path, servers=["lab"])
    args = {
        "media": "sandbox:lab/out/plot.png",
        "attachments": ["local.txt", "sandbox:lab//etc/conf", "sandbox:lab/notes.txt"],
        "text": "sandbox:lab/out/plot.png",
        "out": "sandbox:lab/out/plot.png",
    }
    original = {k: (list(v) if isinstance(v, list) else v) for k, v in args.items()}
    new = await _call(plugin, SendTool(), args, tmp_path)

    copies = tmp_path / ".kt-sandbox" / "lab"
    assert new["media"] == str(copies / "work" / "out" / "plot.png")
    assert Path(new["media"]).read_bytes() == b"PNG-DATA"
    assert new["attachments"] == [
        "local.txt",
        str(copies / "etc" / "conf"),
        str(copies / "work" / "notes.txt"),
    ]
    assert Path(new["attachments"][1]).read_bytes() == b"conf"
    assert new["text"] == "sandbox:lab/out/plot.png"
    assert new["out"] == "sandbox:lab/out/plot.png"
    assert args == original


async def test_builtin_read_tool_path(lab, tmp_path):
    plugin = await _loaded(tmp_path, servers=["lab"])
    new = await _call(plugin, ReadTool(), {"path": "sandbox:lab/notes.txt"}, tmp_path)
    assert Path(new["path"]).read_bytes() == b"notes"


async def test_nothing_to_do_returns_none(lab, tmp_path):
    plugin = await _loaded(tmp_path, servers=["lab"])
    assert await _call(plugin, SendTool(), {"media": "a.png"}, tmp_path) is None
    assert (
        await _call(plugin, PlainTool(), {"media": "sandbox:lab/notes.txt"}, tmp_path)
        is None
    )
    assert not (tmp_path / ".kt-sandbox").exists()


async def test_no_servers_means_the_plugin_does_nothing(lab, tmp_path):
    plugin = await _loaded(tmp_path)
    args = {"media": "sandbox:lab/notes.txt"}
    assert await _call(plugin, SendTool(), args, tmp_path) is None


async def test_server_not_in_servers_is_blocked(lab, tmp_path):
    plugin = await _loaded(tmp_path, servers=["lab"])
    with pytest.raises(PluginBlockError) as info:
        await _call(plugin, SendTool(), {"media": "sandbox:other/a.png"}, tmp_path)
    message = str(info.value)
    assert "sandbox:other/..." in message
    assert "known: lab" in message


async def test_server_listed_but_missing_from_registry(lab, tmp_path):
    plugin = await _loaded(tmp_path, servers=["lab", "ghost"])
    with pytest.raises(PluginBlockError, match="no MCP server named 'ghost'"):
        await _call(plugin, SendTool(), {"media": "sandbox:ghost/a"}, tmp_path)


async def test_errors_become_block_messages(lab, tmp_path, monkeypatch):
    plugin = await _loaded(tmp_path, servers=["lab", "oldlab"], max_bytes=4)
    tool = SendTool()
    with pytest.raises(PluginBlockError, match="over 4"):
        await _call(plugin, tool, {"media": "sandbox:lab/notes.txt"}, tmp_path)
    with pytest.raises(PluginBlockError, match="no file nope in lab"):
        await _call(plugin, tool, {"media": "sandbox:lab/nope"}, tmp_path)
    with pytest.raises(PluginBlockError, match="not a regular file"):
        await _call(plugin, tool, {"media": "sandbox:lab/out"}, tmp_path)
    with pytest.raises(PluginBlockError, match="kt-sandbox upgrade <sandbox>"):
        await _call(plugin, tool, {"media": "sandbox:oldlab/notes.txt"}, tmp_path)
    with pytest.raises(PluginBlockError, match=r"\.\."):
        await _call(plugin, tool, {"media": "sandbox:lab/../x"}, tmp_path)
    monkeypatch.setenv("LAB_TOKEN", "wrong-value")
    with pytest.raises(PluginBlockError) as info:
        await _call(plugin, tool, {"media": "sandbox:lab/notes.txt"}, tmp_path)
    assert "check the headers of MCP server lab" in str(info.value)
    assert "wrong-value" not in str(info.value)
    monkeypatch.delenv("LAB_TOKEN")
    with pytest.raises(PluginBlockError) as info:
        await _call(plugin, tool, {"media": "sandbox:lab/notes.txt"}, tmp_path)
    assert "LAB_TOKEN" in str(info.value)
    assert not (tmp_path / ".kt-sandbox" / "lab" / "x").exists()


async def test_no_header_value_in_messages_or_logs(lab, tmp_path, caplog):
    plugin = await _loaded(tmp_path, servers=["lab"])
    caplog.set_level("DEBUG")
    await _call(plugin, SendTool(), {"media": "sandbox:lab/notes.txt"}, tmp_path)
    with pytest.raises(PluginBlockError) as info:
        await _call(plugin, SendTool(), {"media": "sandbox:lab/nope"}, tmp_path)
    assert lab.token not in str(info.value)
    assert lab.token not in caplog.text


async def test_stdio_sandbox(lab, fake_docker, tmp_path):
    (fake_docker.root / "work" / "a.txt").write_bytes(b"from-vm")
    plugin = await _loaded(tmp_path, servers=["vm"])
    new = await _call(plugin, SendTool(), {"media": "sandbox:vm/a.txt"}, tmp_path)
    assert Path(new["media"]).read_bytes() == b"from-vm"
    assert fake_docker.calls()[-1]["argv"][:3] == [
        "exec",
        "sandbox-vm",
        "kt-sandbox-file",
    ]


async def test_unload_removes_the_copies(lab, tmp_path):
    plugin = await _loaded(tmp_path, servers=["lab"])
    keep = tmp_path / "keep.txt"
    keep.write_text("mine", encoding="utf-8")
    new = await _call(plugin, SendTool(), {"media": "sandbox:lab/notes.txt"}, tmp_path)
    assert Path(new["media"]).exists()
    await plugin.on_unload()
    assert not (tmp_path / ".kt-sandbox").exists()
    assert keep.read_text(encoding="utf-8") == "mine"


async def test_unload_keeps_files_it_did_not_write(lab, tmp_path):
    plugin = await _loaded(tmp_path, servers=["lab"])
    other = tmp_path / ".kt-sandbox" / "elsewhere.txt"
    other.parent.mkdir()
    other.write_text("x", encoding="utf-8")
    await _call(plugin, SendTool(), {"media": "sandbox:lab/notes.txt"}, tmp_path)
    await plugin.on_unload()
    assert other.exists()
    assert not (tmp_path / ".kt-sandbox" / "lab").exists()


async def test_prompt_is_present_only_with_servers(tmp_path):
    ctx = PluginContext(agent_name="a", working_dir=tmp_path)
    assert SandboxFilesPlugin().get_prompt_content(ctx) is None
    text = SandboxFilesPlugin(servers=["lab", "vm"]).get_prompt_content(ctx)
    assert text.startswith("## Sandbox files")
    assert "`sandbox:<server>/<path>`" in text
    assert "`lab`, `vm`" in text
    assert len(text.splitlines()) <= 3


def test_options_validate_and_update():
    plugin = SandboxFilesPlugin()
    assert plugin.get_options() == {"servers": [], "max_bytes": 20 * 1024 * 1024}
    plugin.set_options({"servers": ["lab"], "max_bytes": 10})
    assert plugin.get_options() == {"servers": ["lab"], "max_bytes": 10}
    with pytest.raises(ValueError):
        plugin.set_options({"max_bytes": 0})


class RecordingSandbox(SandboxPlugin):
    """The built-in ``sandbox`` plugin, recording the arguments its path check saw."""

    seen: list[dict] = []

    async def pre_tool_execute(self, args: dict, **kwargs: Any) -> dict | None:
        type(self).seen.append(dict(args))
        return await super().pre_tool_execute(args, **kwargs)


async def test_runs_before_the_builtin_sandbox(lab, tmp_path):
    assert SandboxFilesPlugin.priority < SandboxPlugin.priority
    manager = PluginManager()
    manager.register(RecordingSandbox())
    manager.register(SandboxFilesPlugin(servers=["lab"]))
    await manager.load_all(PluginContext(agent_name="a", working_dir=tmp_path))
    tool = SendTool()
    received: list[dict] = []

    async def execute(args: dict, **kwargs: Any) -> str:
        received.append(args)
        return "ok"

    wrapped = manager.wrap_method(
        "pre_tool_execute",
        "post_tool_execute",
        execute,
        input_kwarg="args",
        extra_kwargs={
            "tool_name": tool.tool_name,
            "tool": tool,
            "job_id": "j",
            "context": _ctx(tmp_path),
        },
    )
    await wrapped({"media": "sandbox:lab/notes.txt"})
    local = str(tmp_path / ".kt-sandbox" / "lab" / "work" / "notes.txt")
    assert RecordingSandbox.seen[-1] == {"media": local}
    assert received == [{"media": local}]
