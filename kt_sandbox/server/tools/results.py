"""Turn a KohakuTerrarium ``ToolResult`` into an MCP tool result."""

import re

from kohakuterrarium.modules.tool.base import ToolResult
from mcp import types

from kt_sandbox.server.tools.runner import cap_text

_DATA_URL = re.compile(r"^data:(?P<mime>[\w.+-]+/[\w.+-]+);base64,(?P<data>.*)$", re.S)


def _content(part, output_bytes: int | None) -> types.TextContent | types.ImageContent:
    """One part of a multimodal result: text stays text, a ``data:`` image becomes an image."""
    if getattr(part, "type", None) == "image_url":
        found = _DATA_URL.match(part.url)
        if found:
            return types.ImageContent(
                type="image", data=found["data"], mimeType=found["mime"]
            )
        return types.TextContent(type="text", text=f"[image: {part.url}]")
    return _text(getattr(part, "text", ""), output_bytes)


def _text(text: str, output_bytes: int | None) -> types.TextContent:
    if output_bytes is not None:
        text = cap_text(text, output_bytes)
    return types.TextContent(type="text", text=text)


def to_call_result(
    result: ToolResult, output_bytes: int | None
) -> types.CallToolResult:
    """Return ``result`` as MCP content, each text part capped at ``output_bytes``.

    A result with an ``error`` is an MCP error whose first text is the error
    message, followed by any output the tool produced (a failed command's
    output, for example). ``output_bytes`` of None leaves text as it is, for a
    tool that already capped its output.
    """
    if isinstance(result.output, str):
        content = [_text(result.output, output_bytes)] if result.output else []
    else:
        content = [_content(part, output_bytes) for part in result.output]
    if result.error:
        return types.CallToolResult(
            content=[_text(result.error, output_bytes), *content], isError=True
        )
    return types.CallToolResult(content=content, isError=False)
