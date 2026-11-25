"""Unit tests for :mod:`kt_sandbox.cli.export` and :mod:`kt_sandbox.cli.import_`."""

from pathlib import Path

from kt_sandbox.cli import export, import_, main
from kt_sandbox.manager.archive import LoadedImage


class FakeManager:
    def __init__(self, loaded=()):
        self.loaded = list(loaded)
        self.calls = []

    def export_image(self, reference, path, *, force=False):
        self.calls.append(("export", reference, path, force))
        return 12_400_000

    def import_images(self, path):
        self.calls.append(("import", path))
        return self.loaded


def test_export_prints_the_size_and_passes_force(monkeypatch, capsys):
    fake = FakeManager()
    monkeypatch.setattr(export, "open_manager", lambda: fake)
    assert main(["export", "lab:v1", "out/lab.tar.gz", "--force"]) == 0
    assert fake.calls == [("export", "lab:v1", Path("out/lab.tar.gz"), True)]
    out = capsys.readouterr().out
    assert "exported lab:v1 to out/lab.tar.gz (12 MB)" in out
    assert "kt-sandbox import lab.tar.gz" in out


def test_import_lists_the_images_and_how_to_open_one(monkeypatch, capsys):
    fake = FakeManager([LoadedImage("lab:v1", True)])
    monkeypatch.setattr(import_, "open_manager", lambda: fake)
    assert main(["import", "lab.tar"]) == 0
    assert fake.calls == [("import", Path("lab.tar"))]
    out = capsys.readouterr().out
    assert "loaded lab:v1" in out and "--from lab:v1" in out
    assert "not saved by kt-sandbox" not in out


def test_import_says_when_an_image_was_not_saved_by_kt_sandbox():
    lines = import_.report(
        [LoadedImage("lab:v1", True), LoadedImage("python:3.12", False)]
    )
    assert lines[:2] == ["loaded lab:v1", "loaded python:3.12"]
    flagged = [line for line in lines if "not saved by kt-sandbox" in line]
    assert len(flagged) == 1 and "python:3.12" in flagged[0]


def test_an_empty_tarball_is_reported():
    assert import_.report([]) == ["the file held no images."]
