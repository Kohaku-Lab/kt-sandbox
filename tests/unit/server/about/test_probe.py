"""Unit tests for :mod:`kt_sandbox.server.about.probe`."""

import math
import os
from pathlib import Path

import pytest

from kt_sandbox.server.about import probe


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def dist(site: Path, name: str, version: str, *requires: str) -> None:
    lines = ["Metadata-Version: 2.1", f"Name: {name}", f"Version: {version}"]
    lines += [f"Requires-Dist: {req}" for req in requires]
    folder = site / f"{name.replace('-', '_')}-{version}.dist-info"
    write(folder / "METADATA", "\n".join(lines) + "\n")


class TestCgroupV2:
    @pytest.fixture
    def cgroup(self, tmp_path):
        write(tmp_path / "cgroup.controllers", "cpu memory pids\n")
        write(tmp_path / "memory.current", "43253760\n")
        write(tmp_path / "memory.max", "268435456\n")
        write(tmp_path / "pids.current", "7\n")
        write(tmp_path / "pids.max", "64\n")
        write(tmp_path / "cpu.max", "50000 100000\n")
        return tmp_path

    def test_limits_and_usage(self, cgroup):
        assert probe.memory(cgroup) == probe.Gauge(43253760, 268435456)
        assert probe.tasks(cgroup) == probe.Gauge(7, 64)
        assert probe.cpus(cgroup) == 0.5

    def test_max_means_no_ceiling(self, cgroup):
        write(cgroup / "memory.max", "max\n")
        write(cgroup / "pids.max", "max\n")
        write(cgroup / "cpu.max", "max 100000\n")
        assert probe.memory(cgroup).limit == math.inf
        assert probe.tasks(cgroup).limit == math.inf
        assert probe.cpus(cgroup) == math.inf


class TestCgroupV1:
    def test_the_v1_files_are_read_when_v2_is_absent(self, tmp_path):
        write(tmp_path / "memory" / "memory.usage_in_bytes", "1048576\n")
        write(tmp_path / "memory" / "memory.limit_in_bytes", "2097152\n")
        write(tmp_path / "pids" / "pids.current", "3\n")
        write(tmp_path / "pids" / "pids.max", "max\n")
        write(tmp_path / "cpu" / "cpu.cfs_quota_us", "200000\n")
        write(tmp_path / "cpu" / "cpu.cfs_period_us", "100000\n")
        assert probe.memory(tmp_path) == probe.Gauge(1048576, 2097152)
        assert probe.tasks(tmp_path) == probe.Gauge(3, math.inf)
        assert probe.cpus(tmp_path) == 2.0

    def test_the_v1_no_limit_values(self, tmp_path):
        write(tmp_path / "memory" / "memory.usage_in_bytes", "1\n")
        write(tmp_path / "memory" / "memory.limit_in_bytes", "9223372036854771712\n")
        write(tmp_path / "cpu" / "cpu.cfs_quota_us", "-1\n")
        write(tmp_path / "cpu" / "cpu.cfs_period_us", "100000\n")
        assert probe.memory(tmp_path).limit == math.inf
        assert probe.cpus(tmp_path) == math.inf


class TestUnknown:
    def test_missing_files_are_unknown_not_errors(self, tmp_path):
        assert probe.memory(tmp_path) == probe.Gauge(None, None)
        assert probe.tasks(tmp_path) == probe.Gauge(None, None)
        assert probe.cpus(tmp_path) is None
        assert probe.processes(tmp_path / "nowhere") is None
        assert probe.disk(tmp_path / "nowhere") is None

    def test_garbage_is_unknown(self, tmp_path):
        write(tmp_path / "memory.current", "lots\n")
        write(tmp_path / "memory.max", "\n")
        write(tmp_path / "cpu.max", "half\n")
        assert probe.memory(tmp_path) == probe.Gauge(None, None)
        assert probe.cpus(tmp_path) is None


def test_processes_count_the_numbered_folders(tmp_path):
    for entry in ("1", "27", "300"):
        (tmp_path / entry).mkdir()
    (tmp_path / "self").mkdir()
    write(tmp_path / "42", "a file, not a process\n")
    assert probe.processes(tmp_path) == 3


def test_disk_is_free_and_total(tmp_path):
    free, total = probe.disk(tmp_path)
    assert 0 < free <= total


class TestPrograms:
    def test_found_only_when_executable_on_the_path(self, tmp_path):
        for name, mode in (("python3", 0o755), ("git", 0o755), ("node", 0o644)):
            write(tmp_path / name, "#!/bin/sh\n").chmod(mode)
        found = probe.programs(str(tmp_path))
        assert list(found) == list(probe.PROGRAMS)
        assert found["python3"] and found["git"]
        assert not found["node"] and not found["ffmpeg"]

    def test_programs_are_looked_up_not_run(self, tmp_path):
        marker = tmp_path / "ran"
        write(tmp_path / "bin" / "git", f"#!/bin/sh\ntouch {marker}\n").chmod(0o755)
        assert probe.programs(str(tmp_path / "bin"))["git"] is True
        assert not marker.exists()

    def test_an_empty_path_finds_nothing(self):
        assert not any(probe.programs("").values())


class TestImageInfo:
    def test_tiers_in_order_without_repeats_or_blanks(self, tmp_path):
        write(tmp_path / "tiers", "slim\n\n data \nslim\nbrowser\n")
        assert probe.tiers(tmp_path) == ["slim", "data", "browser"]

    def test_no_tiers_file_is_unknown(self, tmp_path):
        assert probe.tiers(tmp_path) is None

    def test_notes_of_the_present_tiers_that_have_one(self, tmp_path):
        write(tmp_path / "notes" / "slim.md", "Use python3.\n")
        write(tmp_path / "notes" / "browser.md", "Launch chromium.\n")
        write(tmp_path / "notes" / "media.md", "ffmpeg.\n")
        assert probe.notes(tmp_path, ["slim", "data", "browser"]) == {
            "slim": "Use python3.",
            "browser": "Launch chromium.",
        }

    def test_a_tier_name_cannot_reach_outside_the_notes(self, tmp_path):
        write(tmp_path / "secret.md", "nope\n")
        write(tmp_path / "notes" / "slim.md", "ok\n")
        assert probe.notes(tmp_path, ["../secret", "slim"]) == {"slim": "ok"}


class TestPackages:
    @pytest.fixture
    def runtime(self, tmp_path):
        folder = tmp_path / "runtime"
        write(
            folder / "runtime-requirements.txt",
            "# comment\nmcp>=1.28.1,<2\nPillow>=11.0.0\n\n",
        )
        write(
            folder / "runtime-requirements-no-deps.txt",
            "# installed with --no-deps\nkohakuterrarium==2.2.3\n",
        )
        return folder

    @pytest.fixture
    def site(self, tmp_path):
        site = tmp_path / "site"
        dist(site, "mcp", "1.28.1", "anyio>=4", "pydantic>=2; python_version >= '3'")
        dist(site, "anyio", "4.6.0", "idna", "trio; extra == 'trio'")
        dist(site, "idna", "3.10")
        dist(site, "pydantic", "2.9.0", "typing_extensions")
        dist(site, "typing_extensions", "4.12.0")
        dist(site, "Pillow", "11.0.0")
        dist(site, "kohakuterrarium", "2.2.3", "httpx", "numpy", "trio")
        dist(site, "trio", "0.27.0")
        dist(site, "pandas", "2.2.3", "numpy>=1.26")
        dist(site, "numpy", "2.1.0")
        dist(site, "pip", "25.0")
        dist(site, "kt-sandbox", "0.1.0", "mcp")
        return site

    def test_the_server_and_everything_it_needs_are_set_apart(self, site, runtime):
        found = probe.packages((str(site),), runtime)
        assert found.others == [
            ("numpy", "2.1.0"),
            ("pandas", "2.2.3"),
            ("trio", "0.27.0"),
        ]
        assert found.server == [
            ("kohakuterrarium", "2.2.3"),
            ("mcp", "1.28.1"),
            ("Pillow", "11.0.0"),
        ]

    def test_what_a_no_deps_package_declares_is_not_set_apart(self, site, runtime):
        others = [name for name, _ in probe.packages((str(site),), runtime).others]
        assert "numpy" in others and "trio" in others

    def test_extras_the_server_asks_for_are_followed(self, site, runtime):
        dist(site, "mcp", "1.28.1", "anyio>=4", "pyjwt[crypto]>=2.10")
        dist(
            site,
            "pyjwt",
            "2.10.1",
            'cryptography>=3.4; extra == "crypto"',
            "sphinx; extra == 'docs'",
        )
        dist(site, "cryptography", "45.0", "cffi>=1.14")
        dist(site, "cffi", "1.17", "pycparser")
        dist(site, "pycparser", "2.22")
        dist(site, "sphinx", "8.0")
        others = [name for name, _ in probe.packages((str(site),), runtime).others]
        assert not {"pyjwt", "cryptography", "cffi", "pycparser"} & set(others)
        assert "sphinx" in others

    def test_the_first_copy_on_the_path_wins(self, tmp_path, site, runtime):
        user = tmp_path / "user"
        dist(user, "numpy", "2.3.0")
        found = probe.packages((str(user), str(site)), runtime)
        assert ("numpy", "2.3.0") in found.others
        assert ("numpy", "2.1.0") not in found.others

    def test_without_runtime_files_nothing_is_set_apart_but_the_tooling(
        self, tmp_path, site
    ):
        found = probe.packages((str(site),), tmp_path / "missing")
        names = [name for name, _ in found.others]
        assert "mcp" in names and "anyio" in names
        assert "pip" not in names and "kt-sandbox" not in names
        assert found.server == []

    def test_the_packaged_runtime_files_exist(self):
        for file in probe.RUNTIME_FILES:
            assert (probe.RUNTIME_DIR / file).is_file()

    def test_this_environment_lists_its_server_packages(self):
        found = probe.packages()
        assert "mcp" in [name for name, _ in found.server]
        assert "mcp" not in [name for name, _ in found.others]


def test_the_defaults_point_at_the_image_and_the_system():
    sources = probe.Sources()
    assert sources.cgroup == Path("/sys/fs/cgroup") and sources.proc == Path("/proc")
    assert sources.image_info == probe.IMAGE_INFO_DIR
    assert sources.search_path is None and sources.site_paths is None
    assert os.fspath(probe.IMAGE_INFO_DIR) == "/usr/local/share/kt-sandbox"
