"""Unit tests for the export and import parts of :mod:`kt_sandbox.manager.docker.images`."""

import gzip
from types import SimpleNamespace

import pytest
from docker.errors import ImageLoadError, ImageNotFound

from kt_sandbox.errors import ManagerError
from kt_sandbox.manager import archive
from kt_sandbox.manager.docker import images


class FakeImage:
    def __init__(self, tags, labels=None, short_id="sha256:abc123"):
        self.tags = tags
        self.labels = labels
        self.short_id = short_id
        self.saved_as = None

    def save(self, named=False):
        self.saved_as = named
        yield b"tar-bytes"


class FakeImages:
    def __init__(self, known=None, loads=None, error=None):
        self.known = known or {}
        self.loads = loads or []
        self.error = error
        self.received = None

    def get(self, reference):
        if reference not in self.known:
            raise ImageNotFound(reference)
        return self.known[reference]

    def load(self, stream):
        self.received = stream.read()
        if self.error:
            raise self.error
        return self.loads


def client(**kwargs):
    return SimpleNamespace(images=FakeImages(**kwargs))


class TestTagToSave:
    def test_the_named_tag_is_kept(self):
        image = FakeImage(["lab:v1", "lab:latest"])
        assert images.tag_to_save(image, "lab:latest") == "lab:latest"

    def test_a_bare_name_means_latest(self):
        assert images.tag_to_save(FakeImage(["x:1", "lab:latest"]), "lab") == (
            "lab:latest"
        )

    def test_an_id_falls_back_to_the_first_tag(self):
        assert images.tag_to_save(FakeImage(["lab:v1"]), "sha256:abc") is True


class TestExport:
    def test_streams_the_image_under_its_tag(self, tmp_path):
        image = FakeImage(["lab:v1"])
        path = tmp_path / "lab.tar.gz"
        size = images.export(client(known={"lab:v1": image}), "lab:v1", path)
        assert image.saved_as == "lab:v1"
        assert gzip.decompress(path.read_bytes()) == b"tar-bytes"
        assert size == path.stat().st_size

    def test_an_unknown_image_is_refused_and_writes_nothing(self, tmp_path):
        with pytest.raises(ManagerError, match="no image 'ghost'"):
            images.export(client(), "ghost", tmp_path / "ghost.tar")
        assert list(tmp_path.iterdir()) == []

    def test_an_existing_file_is_refused_before_docker_is_asked(self, tmp_path):
        path = tmp_path / "lab.tar"
        path.write_bytes(b"keep")
        with pytest.raises(ManagerError, match="--force"):
            images.export(client(), "ghost", path)
        assert path.read_bytes() == b"keep"


class TestLoad:
    def test_reports_each_tag_and_whether_kt_sandbox_saved_it(self, tmp_path):
        path = tmp_path / "both.tar"
        path.write_bytes(b"tarball")
        fake = client(
            loads=[
                FakeImage(["lab:v1", "lab:latest"], {"kt-sandbox.saved": "1"}),
                FakeImage([], None, short_id="sha256:def456"),
            ]
        )
        loaded = images.load(fake, path)
        assert fake.images.received == b"tarball"
        assert loaded == [
            archive.LoadedImage("lab:v1", True),
            archive.LoadedImage("lab:latest", True),
            archive.LoadedImage("sha256:def456", False),
        ]

    def test_dockers_refusal_becomes_a_manager_error(self, tmp_path):
        path = tmp_path / "bad.tar.gz"
        path.write_bytes(b"junk")
        with pytest.raises(ManagerError, match="could not import"):
            images.load(client(error=ImageLoadError("unexpected EOF")), path)

    def test_a_missing_file_is_refused(self, tmp_path):
        with pytest.raises(ManagerError, match="no file"):
            images.load(client(), tmp_path / "none.tar")
