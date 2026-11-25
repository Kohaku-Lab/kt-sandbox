"""Unit tests for :mod:`kt_sandbox.server.tools.catalog`: the real KohakuTerrarium tools."""

import time

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
from kohakuterrarium.utils.file.guard import FileReadState

from kt_sandbox.server.settings import ServerSettings
from kt_sandbox.server.tools.catalog import Toolbox, clamp_timeout

NAMES = ["bash", "read", "write", "multi_edit", "glob", "grep", "tree"]


@pytest.fixture
def toolbox(tmp_path):
    return Toolbox(ServerSettings(tmp_path, wall_s=2, output_bytes=300))


def texts(result) -> list[str]:
    return [part.text for part in result.content]


class TestClampTimeout:
    @pytest.mark.parametrize(
        "given,expected",
        [(None, 5.0), ("", 5.0), (0, 5.0), (2, 2.0), (2.5, 2.5), (100, 5.0)],
    )
    def test_the_timeout_never_exceeds_the_wall_limit(self, given, expected):
        arguments = {"command": "x"} if given is None else {"timeout": given}
        assert clamp_timeout(arguments, 5.0)["timeout"] == expected

    @pytest.mark.parametrize("bad", [-1, "soon", float("nan")])
    def test_values_the_tool_rejects_are_left_for_it_to_report(self, bad):
        assert clamp_timeout({"timeout": bad}, 5.0)["timeout"] is bad


class TestListing:
    def test_names_descriptions_and_schemas_are_kohakuterriums_own(self, toolbox):
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
        expected = {
            schema.name: (schema.description, schema.parameters)
            for schema in build_tool_schemas(registry)
        }
        assert [tool.name for tool in toolbox.listing] == NAMES
        assert {
            tool.name: (tool.description, tool.inputSchema) for tool in toolbox.listing
        } == expected


class TestCall:
    async def test_an_unknown_tool_names_the_tools_there_are(self, toolbox):
        result = await toolbox.call("exec", {}, FileReadState())
        assert result.isError and "bash, read, write" in texts(result)[0]

    async def test_bash_runs_in_the_work_folder(self, toolbox, tmp_path):
        result = await toolbox.call("bash", {"command": "pwd"}, FileReadState())
        assert not result.isError
        assert texts(result) == [f"{tmp_path.resolve()}\n"]

    async def test_bash_cannot_run_past_the_wall_limit(self, toolbox):
        started = time.monotonic()
        result = await toolbox.call(
            "bash", {"command": "exec sleep 30", "timeout": 100}, FileReadState()
        )
        assert result.isError and texts(result)[0] == "Command timed out after 2s"
        assert time.monotonic() - started < 6

    async def test_run_in_background_is_ignored_and_the_result_arrives(self, toolbox):
        result = await toolbox.call(
            "bash", {"command": "echo now", "run_in_background": True}, FileReadState()
        )
        assert texts(result) == ["now\n"]

    async def test_bash_output_is_capped_once(self, toolbox):
        result = await toolbox.call(
            "bash", {"command": "yes x | head -c 100000"}, FileReadState()
        )
        (text,) = texts(result)
        assert text.count("bytes omitted") == 1 and len(text) < 360

    async def test_file_tools_text_is_capped(self, toolbox, tmp_path):
        (tmp_path / "big.txt").write_text("line\n" * 1000, encoding="utf-8")
        (text,) = texts(
            await toolbox.call("read", {"path": "big.txt"}, FileReadState())
        )
        assert "bytes omitted" in text and len(text.encode()) < 360

    async def test_read_history_belongs_to_one_client(self, toolbox, tmp_path):
        (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
        mine, theirs = FileReadState(), FileReadState()
        await toolbox.call("read", {"path": "a.txt"}, mine)
        refused = await toolbox.call(
            "write", {"path": "a.txt", "content": "two\n"}, theirs
        )
        assert refused.isError and "has not been read yet" in texts(refused)[0]
        allowed = await toolbox.call(
            "write", {"path": "a.txt", "content": "two\n"}, mine
        )
        assert not allowed.isError
        assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "two\n"
