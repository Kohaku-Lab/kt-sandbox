"""Unit tests for :mod:`kt_sandbox.server.tools.results`."""

from kohakuterrarium.llm.message import ImagePart, TextPart
from kohakuterrarium.modules.tool.base import ToolResult

from kt_sandbox.server.tools.results import to_call_result


class TestToCallResult:
    def test_text_output(self):
        result = to_call_result(ToolResult(output="hello", exit_code=0), 100)
        assert not result.isError
        assert [(c.type, c.text) for c in result.content] == [("text", "hello")]

    def test_empty_output_has_no_content(self):
        assert to_call_result(ToolResult(output=""), 100).content == []

    def test_an_error_comes_first_and_the_output_follows(self):
        result = to_call_result(
            ToolResult(output="hi\n", exit_code=4, error="Command exited with code 4"),
            100,
        )
        assert result.isError
        assert [c.text for c in result.content] == [
            "Command exited with code 4",
            "hi\n",
        ]

    def test_an_error_without_output(self):
        result = to_call_result(ToolResult(error="File not found: x"), 100)
        assert result.isError and [c.text for c in result.content] == [
            "File not found: x"
        ]

    def test_a_data_url_image_becomes_image_content(self):
        result = to_call_result(
            ToolResult(
                output=[
                    TextPart(text="Image: a.png (0KB, image/png)"),
                    ImagePart(url="data:image/png;base64,iVBORw0KGgo="),
                ]
            ),
            100,
        )
        text, image = result.content
        assert text.type == "text" and text.text.startswith("Image: a.png")
        assert (image.type, image.mimeType, image.data) == (
            "image",
            "image/png",
            "iVBORw0KGgo=",
        )

    def test_an_image_that_is_not_inline_is_named_as_text(self):
        result = to_call_result(
            ToolResult(output=[ImagePart(url="https://example.org/a.png")]), 100
        )
        assert result.content[0].text == "[image: https://example.org/a.png]"

    def test_text_is_capped_with_the_omitted_marker(self):
        result = to_call_result(ToolResult(output="a" * 60 + "b" * 100 + "c" * 30), 90)
        text = result.content[0].text
        assert text.startswith("a" * 60) and text.endswith("c" * 30)
        assert "[... 100 bytes omitted ...]" in text

    def test_no_cap_leaves_text_whole(self):
        result = to_call_result(ToolResult(output="x" * 500), None)
        assert result.content[0].text == "x" * 500
