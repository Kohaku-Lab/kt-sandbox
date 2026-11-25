"""Unit tests for :mod:`kt_sandbox.manager.archive`."""

import gzip
from pathlib import Path

import pytest

from kt_sandbox.errors import ManagerError
from kt_sandbox.manager import archive

CHUNKS = [b"layer-one " * 1000, b"", b"layer-two " * 500]


class TestWriteChunks:
    def test_a_tar_name_is_written_as_is(self, tmp_path):
        path = tmp_path / "img.tar"
        size = archive.write_chunks(iter(CHUNKS), path)
        assert path.read_bytes() == b"".join(CHUNKS) and size == path.stat().st_size

    @pytest.mark.parametrize("name", ["img.tar.gz", "IMG.TGZ"])
    def test_a_gz_name_is_gzipped(self, tmp_path, name):
        path = tmp_path / name
        size = archive.write_chunks(iter(CHUNKS), path)
        assert path.read_bytes()[:2] == b"\x1f\x8b"
        assert gzip.decompress(path.read_bytes()) == b"".join(CHUNKS)
        assert size == path.stat().st_size < len(b"".join(CHUNKS))

    def test_an_existing_file_is_kept_without_force(self, tmp_path):
        path = tmp_path / "img.tar"
        path.write_bytes(b"precious")
        with pytest.raises(ManagerError, match="--force"):
            archive.write_chunks(iter(CHUNKS), path)
        assert path.read_bytes() == b"precious"

    def test_force_overwrites(self, tmp_path):
        path = tmp_path / "img.tar"
        path.write_bytes(b"old")
        archive.write_chunks(iter([b"new"]), path, force=True)
        assert path.read_bytes() == b"new"

    def test_a_failed_stream_leaves_no_file(self, tmp_path):
        def broken():
            yield b"start"
            raise RuntimeError("engine went away")

        path = tmp_path / "img.tar.gz"
        with pytest.raises(RuntimeError):
            archive.write_chunks(broken(), path)
        assert list(tmp_path.iterdir()) == []

    def test_a_failed_overwrite_keeps_the_old_file(self, tmp_path):
        def broken():
            raise RuntimeError("engine went away")
            yield b""

        path = tmp_path / "img.tar"
        path.write_bytes(b"old")
        with pytest.raises(RuntimeError):
            archive.write_chunks(broken(), path, force=True)
        assert [p.name for p in tmp_path.iterdir()] == ["img.tar"]
        assert path.read_bytes() == b"old"


class TestChecks:
    def test_a_missing_folder_is_refused(self, tmp_path):
        with pytest.raises(ManagerError, match="does not exist"):
            archive.check_destination(tmp_path / "nowhere" / "img.tar")

    def test_a_folder_is_not_a_destination_even_with_force(self, tmp_path):
        with pytest.raises(ManagerError, match="is a folder"):
            archive.check_destination(tmp_path, force=True)

    def test_only_existing_tarballs_can_be_loaded(self, tmp_path):
        with pytest.raises(ManagerError, match="no file"):
            archive.check_source(tmp_path / "img.tar")
        other = tmp_path / "img.zip"
        other.write_bytes(b"x")
        with pytest.raises(ManagerError, match=r"not a \.tar"):
            archive.check_source(other)
        for name in ("a.tar", "b.tar.gz", "c.tgz"):
            (tmp_path / name).write_bytes(b"x")
            archive.check_source(tmp_path / name)

    def test_gzip_is_chosen_by_name(self):
        assert archive.wants_gzip(Path("a.tar.gz")) and archive.wants_gzip(
            Path("a.tgz")
        )
        assert not archive.wants_gzip(Path("a.tar"))
