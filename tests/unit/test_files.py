"""Unit tests for :mod:`kt_sandbox.files`: references, Docker's stat and the tar stream."""

import io
import tarfile

import pytest

from kt_sandbox import files
from kt_sandbox.errors import BadReference, NotAFile, SandboxError, TooLarge
from kt_sandbox.files import (
    MODE_DIR,
    MODE_SYMLINK,
    ChunkStream,
    container_path,
    extract_one,
    parse_ref,
    refuse_by_stat,
)


def tar_of(*members: tuple[tarfile.TarInfo, bytes | None]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for info, data in members:
            archive.addfile(info, io.BytesIO(data) if data is not None else None)
    return buffer.getvalue()


def regular(name: str, data: bytes) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    return info, data


def special(name: str, kind: bytes, link: str = "") -> tuple[tarfile.TarInfo, None]:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = link
    return info, None


def chunks_of(data: bytes, size: int = 1000):
    return [data[i : i + size] for i in range(0, len(data), size)]


class CountingChunks:
    """Chunks that record how many bytes were pulled from them."""

    def __init__(self, data: bytes, size: int = 4096):
        self.parts = chunks_of(data, size)
        self.pulled = 0

    def __iter__(self):
        for part in self.parts:
            self.pulled += len(part)
            yield part


class TestParseRef:
    @pytest.mark.parametrize(
        "ref,expected",
        [
            ("sandbox:lab/out/chart.png", ("lab", "out/chart.png")),
            ("sandbox:lab/a.txt", ("lab", "a.txt")),
            ("sandbox:lab//etc/hosts", ("lab", "/etc/hosts")),
            ("sandbox:3f2a9c/x", ("3f2a9c", "x")),
            ("sandbox:kt-sandbox-lab/a b.txt", ("kt-sandbox-lab", "a b.txt")),
        ],
    )
    def test_good_references(self, ref, expected):
        assert parse_ref(ref) == expected

    @pytest.mark.parametrize(
        "bad",
        [
            "lab/a.txt",
            "sandbox:",
            "sandbox:lab",
            "sandbox:lab/",
            "sandbox:/a.txt",
            "sandbox:-lab/a",
            "sandbox:l@b/a",
            "file:lab/a",
        ],
    )
    def test_bad_references_say_the_form(self, bad):
        with pytest.raises(BadReference, match="sandbox:<name>/<path>") as raised:
            parse_ref(bad)
        assert isinstance(raised.value, SandboxError)


def test_relative_paths_are_under_the_work_folder():
    assert container_path("out/a.png") == "/work/out/a.png"
    assert container_path("/etc/hosts") == "/etc/hosts"


class TestRefuseByStat:
    def test_a_regular_file_within_the_limit_passes(self):
        refuse_by_stat({"mode": 0o644, "size": 10}, "/work/a", "lab", 10)
        refuse_by_stat(None, "/work/a", "lab", 10)

    @pytest.mark.parametrize(
        "stat,message",
        [
            ({"mode": MODE_DIR | 0o755, "size": 4096}, "is a folder"),
            (
                {"mode": MODE_SYMLINK | 0o777, "size": 11, "linkTarget": "/etc/passwd"},
                "symbolic link to /etc/passwd",
            ),
            ({"mode": (1 << 25) | 0o644, "size": 0}, "not a regular file"),
            ({"mode": (1 << 26) | (1 << 21), "size": 0}, "not a regular file"),
        ],
    )
    def test_anything_but_a_regular_file_is_refused(self, stat, message):
        with pytest.raises(NotAFile, match=message):
            refuse_by_stat(stat, "/work/x", "lab", 1000)

    def test_an_oversize_file_is_refused_with_its_size_and_a_next_step(self):
        with pytest.raises(TooLarge, match="is 11 bytes, over the 10-byte limit"):
            refuse_by_stat({"mode": 0o644, "size": 11}, "/work/a", "lab", 10)


class TestExtractOne:
    def test_the_file_comes_back_with_its_name(self):
        data = tar_of(regular("chart.png", b"\x89PNG..."))
        assert extract_one(chunks_of(data), "/work/chart.png", "lab", 100) == (
            "chart.png",
            b"\x89PNG...",
        )

    def test_a_file_of_exactly_the_limit_is_read(self):
        data = tar_of(regular("a", b"x" * 5000))
        assert extract_one(chunks_of(data, 700), "/work/a", "lab", 5000)[1] == (
            b"x" * 5000
        )

    @pytest.mark.parametrize(
        "member,message",
        [
            (special("link", tarfile.SYMTYPE, "/etc/passwd"), "link to /etc/passwd"),
            (special("hard", tarfile.LNKTYPE, "other"), "link to other"),
            (special("d", tarfile.DIRTYPE), "is a folder"),
            (special("p", tarfile.FIFOTYPE), "not a regular file"),
            (special("c", tarfile.CHRTYPE), "not a regular file"),
        ],
    )
    def test_anything_but_a_regular_file_is_refused(self, member, message):
        with pytest.raises(NotAFile, match=message):
            extract_one(chunks_of(tar_of(member)), "/work/x", "lab", 100)

    def test_an_oversize_member_is_refused_before_its_data_is_read(self):
        source = CountingChunks(tar_of(regular("big", b"x" * 2_000_000)))
        with pytest.raises(TooLarge, match="2000000 bytes, over the 1000-byte"):
            extract_one(source, "/work/big", "lab", 1000)
        assert source.pulled < 64 * 1024

    def test_a_stream_longer_than_its_header_says_stops_at_the_budget(self):
        info, _ = regular("liar", b"")
        info.size = 100
        lying = tar_of((info, b"y" * 100)) + b"z" * 3_000_000
        source = CountingChunks(lying)
        name, data = extract_one(source, "/work/liar", "lab", 100)
        assert (name, data) == ("liar", b"y" * 100)
        assert source.pulled < files.TAR_OVERHEAD + 10_000

    def test_an_empty_archive_is_reported(self):
        with pytest.raises(SandboxError, match="came back empty"):
            extract_one(chunks_of(tar_of()), "/work/x", "lab", 100)


class TestChunkStream:
    def test_reads_across_chunks(self):
        stream = io.BufferedReader(ChunkStream([b"ab", b"", b"cde"], budget=100))
        assert stream.read() == b"abcde"

    def test_stops_pulling_at_the_budget(self):
        source = CountingChunks(b"x" * 100_000, size=1000)
        stream = ChunkStream(source, budget=5000)
        buffer = bytearray(1000)
        with pytest.raises(files._Overflow):
            while stream.readinto(buffer):
                pass
        assert source.pulled == 5000
