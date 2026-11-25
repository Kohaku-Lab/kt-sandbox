"""``sandbox:<server>/<path>`` handles: parsing, the path sent to the sandbox and the local copy's place."""

from pathlib import PurePosixPath

import pytest

from kt_sandbox.kt_plugin.errors import SandboxFileError
from kt_sandbox.kt_plugin.handle import is_handle, parse_handle


def test_relative_path_is_sent_as_is_and_kept_under_work():
    handle = parse_handle("sandbox:lab/out/plot.png")
    assert handle.server == "lab"
    assert handle.remote == "out/plot.png"
    assert handle.local == PurePosixPath("work/out/plot.png")


def test_double_slash_is_an_absolute_path():
    handle = parse_handle("sandbox:lab//tmp/a.txt")
    assert handle.remote == "/tmp/a.txt"
    assert handle.local == PurePosixPath("tmp/a.txt")


def test_relative_and_absolute_copies_do_not_collide():
    assert parse_handle("sandbox:lab/a").local != parse_handle("sandbox:lab//a").local


def test_dot_segments_are_dropped_locally():
    assert parse_handle("sandbox:lab/./a/./b").local == PurePosixPath("work/a/b")


@pytest.mark.parametrize(
    "text",
    [
        "sandbox:lab/../etc/passwd",
        "sandbox:lab//work/../../etc/passwd",
        "sandbox:lab/a/..",
        "sandbox:lab/a\\..\\..\\b",
    ],
)
def test_parent_segments_are_refused(text):
    with pytest.raises(SandboxFileError, match=r"\.\."):
        parse_handle(text)


@pytest.mark.parametrize(
    "text", ["sandbox:", "sandbox:lab", "sandbox:lab/", "sandbox:/x", "sandbox:lab//"]
)
def test_missing_server_or_path_is_refused(text):
    with pytest.raises(SandboxFileError, match="sandbox:<server>/<path>"):
        parse_handle(text)


def test_is_handle_only_matches_strings_with_the_prefix():
    assert is_handle("sandbox:lab/a")
    assert not is_handle("./sandbox:lab/a")
    assert not is_handle("notes/sandbox:lab")
    assert not is_handle(42)
    assert not is_handle(None)
