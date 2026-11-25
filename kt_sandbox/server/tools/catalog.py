"""The seven KohakuTerrarium tools a sandbox serves, configured for the sandbox's limits."""

import math
from typing import Any

from kohakuterrarium.builtins.tools.bash.bash import BashTool
from kohakuterrarium.builtins.tools.files.glob import GlobTool
from kohakuterrarium.builtins.tools.files.grep import GrepTool
from kohakuterrarium.builtins.tools.files.multi_edit import MultiEditTool
from kohakuterrarium.builtins.tools.files.read import ReadTool
from kohakuterrarium.builtins.tools.files.tree import TreeTool
from kohakuterrarium.builtins.tools.files.write import WriteTool
from kohakuterrarium.core.registry import Registry
from kohakuterrarium.llm.tools.build import build_tool_schemas
from kohakuterrarium.modules.tool.base import BaseTool, ToolConfig, ToolContext
from kohakuterrarium.utils.file.guard import FileReadState
from mcp import types

from kt_sandbox.server.settings import ServerSettings
from kt_sandbox.server.tools.results import to_call_result
from kt_sandbox.server.tools.runner import SubprocessRunner

TOOL_CLASSES: tuple[type[BaseTool], ...] = (
    BashTool,
    ReadTool,
    WriteTool,
    MultiEditTool,
    GlobTool,
    GrepTool,
    TreeTool,
)
EXECUTOR_ARGUMENTS = ("run_in_background",)
AGENT_NAME = "kt-sandbox"


def clamp_timeout(arguments: dict[str, Any], wall_s: float) -> dict[str, Any]:
    """Return ``bash`` arguments whose ``timeout`` is at most ``wall_s``.

    A missing, empty or zero timeout (KohakuTerrarium's "no timeout") becomes
    ``wall_s``. A value the tool would reject (negative, not a number) is left
    for the tool to report.
    """
    raw = arguments.get("timeout")
    if raw in (None, "", 0):
        return {**arguments, "timeout": wall_s}
    try:
        requested = float(raw)
    except (TypeError, ValueError):
        return arguments
    if not math.isfinite(requested) or requested < 0:
        return arguments
    return {**arguments, "timeout": min(requested, wall_s)}


class Toolbox:
    """The tool instances, their MCP listing and the calls into them."""

    def __init__(self, settings: ServerSettings):
        self.settings = settings
        config = ToolConfig(
            timeout=float(settings.wall_s), max_output=settings.output_bytes
        )
        self.tools: dict[str, BaseTool] = {}
        registry = Registry()
        for tool_class in TOOL_CLASSES:
            tool = tool_class(config)
            self.tools[tool.tool_name] = tool
            registry.register_tool(tool)
        self.listing = [
            types.Tool(
                name=schema.name,
                description=schema.description,
                inputSchema=schema.parameters,
            )
            for schema in build_tool_schemas(registry)
        ]
        self.runner = SubprocessRunner(settings.wall_s, settings.output_bytes)

    def context(self, file_read_state: FileReadState) -> ToolContext:
        """Return the context a call runs in: the work folder and one client's read history."""
        return ToolContext(
            agent_name=AGENT_NAME,
            session=None,
            working_dir=self.settings.workdir,
            file_read_state=file_read_state,
            runtime_services={"subprocess_runner": self.runner},
        )

    async def call(
        self, name: str, arguments: dict[str, Any], file_read_state: FileReadState
    ) -> types.CallToolResult:
        """Run tool ``name`` and return its result as MCP content."""
        tool = self.tools.get(name)
        if tool is None:
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=f"no tool {name!r}; the tools are {', '.join(self.tools)}",
                    )
                ],
                isError=True,
            )
        arguments = {
            key: value
            for key, value in arguments.items()
            if key not in EXECUTOR_ARGUMENTS
        }
        if name == "bash":
            arguments = clamp_timeout(arguments, float(self.settings.wall_s))
        result = await tool.execute(arguments, context=self.context(file_read_state))
        # bash output is already capped by the runner while it is read.
        cap = None if name == "bash" else self.settings.output_bytes
        return to_call_result(result, cap)
