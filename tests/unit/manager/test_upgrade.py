"""Unit tests for :mod:`kt_sandbox.manager.upgrade` and ``kt-sandbox upgrade``."""

import io
import os
import re
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import pytest
from docker.errors import APIError
from docker.errors import NotFound as DockerNotFound

from kt_sandbox.cli import main, upgrade as upgrade_cli
from kt_sandbox.errors import ManagerError
from kt_sandbox.manager import upgrade
from kt_sandbox.manager.builder import BUILD_DIR, PACKAGE_DIR
from kt_sandbox.manager.sandboxes import Manager


class FakeContainer:
    """A container that records what the archive and exec APIs were given."""

    def __init__(
        self, name="lab", status="running", read_only=False, labelled=True, missing=""
    ):
        self.missing = missing
        self.name = f"kt-sandbox-{name}"
        self.status = status
        self.labels = {"kt-sandbox.name": name} if labelled else {}
        self.attrs = {"HostConfig": {"ReadonlyRootfs": read_only}}
        self.archives: list[tuple[str, bytes]] = []
        self.execs: list[tuple[list[str], str]] = []
        self.refuse = None

    def put_archive(self, path, data):
        if self.refuse:
            raise self.refuse
        self.archives.append((path, data))
        return True

    def exec_run(self, cmd, user=""):
        self.execs.append((cmd, user))
        if cmd[:2] == ["python", "-c"] and self.missing:
            return SimpleNamespace(exit_code=1, output=self.missing.encode() + b"\n")
        return SimpleNamespace(exit_code=0, output=b"")


def members(data: bytes) -> list[tarfile.TarInfo]:
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        return archive.getmembers()


def read_member(data: bytes, name: str) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        return archive.extractfile(name).read()


@pytest.fixture(scope="module")
def data():
    return upgrade.archive()


class TestArchive:
    def test_the_old_package_is_replaced_not_merged(self, data):
        found = members(data)
        package = "opt/kt-sandbox/kt_sandbox"
        assert found[0].name == package and found[0].isreg() and found[0].size == 0
        assert found[1].name == package and found[1].isdir()
        assert all(m.name.startswith(package) for m in found[:-4])

    def test_the_package_is_the_installed_one_without_caches(self, data):
        names = {m.name for m in members(data)}
        assert "opt/kt-sandbox/kt_sandbox/server/files.py" in names
        assert "opt/kt-sandbox/kt_sandbox/manager/image/Dockerfile" in names
        assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
        source = (PACKAGE_DIR / "server" / "files.py").read_bytes()
        assert read_member(data, "opt/kt-sandbox/kt_sandbox/server/files.py") == source

    def test_every_entry_belongs_to_root_and_is_world_readable(self, data):
        for member in members(data):
            assert (member.uid, member.gid) == (0, 0)
            assert member.mode & 0o444 == 0o444
            assert member.mode & 0o022 == 0

    def test_the_wrappers(self, data):
        wrappers = {m.name: m for m in members(data)[-4:]}
        assert set(wrappers) == {f"usr/local/bin/{w}" for w in upgrade.WRAPPERS}
        for member in wrappers.values():
            assert member.mode == 0o755
        assert read_member(data, "usr/local/bin/kt-sandbox-file") == (
            b'#!/usr/bin/env python\nimport runpy, sys\nsys.path.insert(0, "/opt/kt-sandbox")\n'
            b'runpy.run_module("kt_sandbox.server.files", run_name="__main__", '
            b"alter_sys=True)\n"
        )


class TestUpgrade:
    def test_a_running_sandbox_gets_the_archive_and_a_compile(self):
        container = FakeContainer()
        result = upgrade.upgrade_container(container)
        assert [path for path, _ in container.archives] == ["/"]
        check, compile_ = container.execs
        assert check[0][:2] == ["python", "-c"]
        assert check[0][3:] == ["kohakuterrarium", "mcp", "starlette", "uvicorn"]
        assert compile_ == (
            ["python", "-m", "compileall", "-q", "/opt/kt-sandbox/kt_sandbox"],
            "root",
        )
        assert result.name == "lab" and result.compiled is result.checked is True
        assert result.files > 50 and result.wrappers == upgrade.WRAPPERS

    def test_a_stopped_sandbox_is_upgraded_without_starting(self):
        container = FakeContainer(status="exited")
        result = upgrade.upgrade_container(container)
        assert len(container.archives) == 1 and container.execs == []
        assert result.compiled is result.checked is False
        assert container.status == "exited"

    def test_a_running_sandbox_missing_a_dependency_is_left_alone(self):
        container = FakeContainer(missing="kohakuterrarium")
        with pytest.raises(
            ManagerError, match=r"\(kohakuterrarium\); its image is too old"
        ):
            upgrade.upgrade_container(container)
        assert container.archives == []

    def test_the_dependency_check_finds_a_missing_module(self):
        done = subprocess.run(
            [sys.executable, "-c", upgrade.FIND_MISSING, "json", "no_such_module_kt"],
            capture_output=True,
            check=False,
        )
        assert (done.returncode, done.stdout) == (1, b"no_such_module_kt\n")

    def test_a_read_only_sandbox_is_refused(self):
        container = FakeContainer(read_only=True)
        with pytest.raises(ManagerError, match="read-only"):
            upgrade.upgrade_container(container)
        assert container.archives == []

    def test_a_container_kt_sandbox_did_not_make_is_refused(self):
        container = FakeContainer(labelled=False)
        with pytest.raises(ManagerError, match="not made by kt-sandbox"):
            upgrade.upgrade_container(container)
        assert container.archives == []

    def test_docker_refusing_the_archive_is_a_manager_error(self):
        container = FakeContainer()
        container.refuse = APIError("no", explanation="disk full")
        with pytest.raises(ManagerError, match="disk full"):
            upgrade.upgrade_container(container)


class FakeClient:
    def __init__(self, *found):
        self.found = {c.name: c for c in found}
        self.containers = SimpleNamespace(get=self.get, list=self.list)

    def get(self, name):
        if name not in self.found:
            raise DockerNotFound(name)
        return self.found[name]

    def list(self, all=False, filters=None):
        return [c for c in self.found.values() if c.labels]


class TestManager:
    def test_upgrade_by_name(self):
        lab = FakeContainer("lab")
        assert Manager(FakeClient(lab)).upgrade("lab").name == "lab"
        assert len(lab.archives) == 1

    def test_an_unknown_name(self):
        with pytest.raises(ManagerError, match="kt-sandbox ls"):
            Manager(FakeClient()).upgrade("ghost")

    def test_upgrade_all_reports_each_and_skips_none(self):
        lab, frozen = FakeContainer("lab"), FakeContainer("frozen", read_only=True)
        done = Manager(FakeClient(lab, frozen)).upgrade_all()
        assert [(name, type(r).__name__) for name, r in done] == [
            ("frozen", "ManagerError"),
            ("lab", "Upgraded"),
        ]
        assert len(lab.archives) == 1 and frozen.archives == []


class TestCommand:
    @pytest.fixture
    def fake(self, monkeypatch):
        lab, frozen = FakeContainer("lab"), FakeContainer("frozen", read_only=True)
        manager = Manager(FakeClient(lab, frozen))
        monkeypatch.setattr(upgrade_cli, "open_manager", lambda: manager)
        return lab

    def test_one(self, fake, capsys):
        assert main(["upgrade", "lab"]) == 0
        out = capsys.readouterr().out
        assert "upgraded lab" in out and "kt-sandbox-file" in out
        assert (
            "docker exec kt-sandbox-lab pkill -f 'kt-sandbox-mcp|kt_sandbox.server'"
            in out
        )
        assert "stdio servers restart on the next connection" in out

    def test_a_refusal_fails(self, fake, capsys):
        assert main(["upgrade", "frozen"]) == 1
        assert "read-only" in capsys.readouterr().err

    def test_all_upgrades_what_it_can_and_fails_on_the_rest(self, fake, capsys):
        assert main(["upgrade", "--all"]) == 1
        captured = capsys.readouterr()
        assert "upgraded lab" in captured.out and "frozen" in captured.err

    def test_a_name_or_all_but_not_both(self, capsys):
        assert main(["upgrade"]) == 2
        assert main(["upgrade", "lab", "--all"]) == 2


def test_the_wrappers_match_the_dockerfile():
    dockerfile = (BUILD_DIR / "Dockerfile").read_text(encoding="utf-8")
    written = dict(
        (command, module)
        for module, command in re.findall(r"wrap ([\w.]+) ([\w-]+);", dockerfile)
    )
    assert written == upgrade.WRAPPERS
    assert upgrade.wrapper_script("%s").decode() in dockerfile.replace("\\n", "\n")


def test_a_wrapper_runs_its_module(tmp_path, monkeypatch):
    script = tmp_path / "kt-sandbox-file"
    script.write_bytes(upgrade.wrapper_script("kt_sandbox.server.files"))
    (tmp_path / "a.txt").write_bytes(b"hello")
    done = subprocess.run(
        [sys.executable, str(script), "a.txt"],
        capture_output=True,
        env={**os.environ, "KT_SANDBOX_WORKDIR": str(tmp_path)},
        check=False,
    )
    assert (done.returncode, done.stdout) == (0, b"hello")
