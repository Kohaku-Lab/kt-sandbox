"""Unit tests for :mod:`kt_sandbox.server.about.document`."""

import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kt_sandbox.server.about import document, probe
from kt_sandbox.server.settings import ServerSettings

NOW = datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc)
STRICT = {
    "KT_SANDBOX_NAME": "bot",
    "KT_SANDBOX_LEVEL": "strict",
    "KT_SANDBOX_NETWORK": "none",
    "KT_SANDBOX_ALLOW": "",
    "KT_SANDBOX_SUDO": "0",
    "KT_SANDBOX_WALL_S": "15",
}


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def sources(tmp_path):
    """A fake sandbox: cgroup v2 files, four processes, a slim+browser image, a PATH."""
    cgroup, proc, info, bin_ = (tmp_path / d for d in ("cg", "proc", "info", "bin"))
    for name, value in {
        "memory.current": "43253760",
        "memory.max": "268435456",
        "pids.current": "7",
        "pids.max": "64",
        "cpu.max": "50000 100000",
    }.items():
        write(cgroup / name, value + "\n")
    for pid in ("1", "8", "9", "12"):
        (proc / pid).mkdir(parents=True)
    write(info / "tiers", "slim\nbrowser\n")
    write(info / "notes" / "slim.md", "CJK fonts are installed.\n")
    write(info / "notes" / "browser.md", "Chromium is `/usr/bin/chromium`.\n")
    for name in ("python3", "curl"):
        write(bin_ / name, "#!/bin/sh\n").chmod(0o755)
    site = tmp_path / "site"
    for name, version in (("mcp", "1.28.1"), ("playwright", "1.65.2")):
        write(
            site / f"{name}-{version}.dist-info" / "METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        )
    runtime = tmp_path / "runtime"
    write(runtime / "runtime-requirements.txt", "mcp>=1\n")
    return probe.Sources(
        cgroup=cgroup,
        proc=proc,
        image_info=info,
        search_path=str(bin_),
        site_paths=(str(site),),
        runtime_dir=runtime,
    )


def strict(tmp_path, **extra) -> ServerSettings:
    return ServerSettings.from_env(
        {**STRICT, "KT_SANDBOX_WORKDIR": str(tmp_path), **extra}
    )


class TestRender:
    def test_a_strict_sandbox(self, tmp_path, sources):
        text = document.render(strict(tmp_path), sources, now=NOW)
        assert text.startswith("# About the sandbox bot\n")
        assert "2026-01-02 03:04 UTC" in text and "`kt-sandbox-about`" in text
        for line in (
            "- Level: strict",
            "- Network: none; the sandbox is offline",
            "- sudo: off",
            "- One command: up to 15 s",
            "- One result: up to 12 KiB of text",
            f"- Work folder: {tmp_path}",
            "- Memory: 41.2 MiB used of 256 MiB",
            "- CPUs: 0.5",
            "- Processes: 4 (tasks, counting threads: 7 of 64)",
            "- Tiers: slim, browser",
            "- Found: python3, curl",
            "- Python packages: playwright 1.65.2",
            "- Used by the server, importable too: mcp 1.28.1",
            "## Notes: slim",
            "CJK fonts are installed.",
            "## Notes: browser",
            "Chromium is `/usr/bin/chromium`.",
        ):
            assert line in text.splitlines(), line
        assert "- Disk: " in text and f"free in {tmp_path}" in text
        not_found = next(l for l in text.splitlines() if l.startswith("- Not found"))
        assert "git" in not_found and "python3" not in not_found
        assert text.index("## Notes: slim") < text.index("## Notes: browser")

    def test_the_network_of_each_level(self, tmp_path, sources):
        allow = document.render(
            strict(
                tmp_path,
                KT_SANDBOX_NETWORK="allowlist",
                KT_SANDBOX_ALLOW="pypi.org,github.com",
            ),
            sources,
        )
        assert (
            "- Network: only pypi.org, github.com, through the proxy set in HTTP_PROXY and HTTPS_PROXY"
            in allow.splitlines()
        )
        opened = document.render(
            strict(tmp_path, KT_SANDBOX_NETWORK="open", KT_SANDBOX_SUDO="1"), sources
        )
        assert "- Network: open" in opened.splitlines()
        assert "- sudo: works without a password" in opened.splitlines()

    def test_without_the_policy_everything_unknown_says_so(self, tmp_path):
        empty = probe.Sources(
            cgroup=tmp_path / "x",
            proc=tmp_path / "x",
            image_info=tmp_path / "x",
            search_path="",
            site_paths=(str(tmp_path / "x"),),
            runtime_dir=tmp_path / "x",
        )
        text = document.render(
            ServerSettings(tmp_path / "missing"), empty, now=NOW
        ).splitlines()
        assert text[0] == "# About this sandbox"
        for line in (
            "- Level: unknown",
            "- Network: unknown",
            "- sudo: unknown",
            "- Memory: unknown",
            "- CPUs: unknown",
            "- Processes: unknown",
            "- Disk: unknown",
            "- Tiers: unknown",
            "- Found: none of the listed programs",
            "- Python packages: none besides the server's",
        ):
            assert line in text, line
        assert not any(l.startswith("## Notes") for l in text)

    def test_no_limits_read_as_no_limit(self, tmp_path, sources):
        write(sources.cgroup / "memory.max", "max\n")
        write(sources.cgroup / "pids.max", "max\n")
        write(sources.cgroup / "cpu.max", "max 100000\n")
        text = document.render(strict(tmp_path), sources).splitlines()
        assert "- Memory: 41.2 MiB used, no limit" in text
        assert "- CPUs: no limit" in text
        assert "- Processes: 4 (tasks, counting threads: 7, no limit)" in text

    def test_a_section_that_fails_says_unknown_and_the_rest_renders(
        self, tmp_path, sources, monkeypatch
    ):
        def broken(*_):
            raise RuntimeError("boom")

        monkeypatch.setattr(probe, "packages", broken)
        text = document.render(strict(tmp_path), sources)
        assert "## Python" in text and "- unknown" in text
        assert "- Level: strict" in text and "boom" not in text

    def test_no_secret_in_the_environment_reaches_the_document(
        self, tmp_path, sources, monkeypatch
    ):
        secrets = {
            "HTTP_PROXY": "http://bot:egress-s3cret-1@kt-sandbox-egress:3128",
            "HTTPS_PROXY": "http://bot:egress-s3cret-1@kt-sandbox-egress:3128",
            "KT_SANDBOX_EGRESS_SECRET": "egress-s3cret-1",
            "KT_SANDBOX_MCP_TOKEN": "mcp-t0ken-2",
            "OPENAI_API_KEY": "sk-key-3",
        }
        for key, value in secrets.items():
            monkeypatch.setenv(key, value)
        settings = ServerSettings.from_env(
            {
                **STRICT,
                **secrets,
                "KT_SANDBOX_NETWORK": "allowlist",
                "KT_SANDBOX_ALLOW": "pypi.org",
                "KT_SANDBOX_WORKDIR": str(tmp_path),
            }
        )
        text = document.render(settings, sources)
        for needle in ("s3cret", "t0ken", "sk-key", "egress:3128", "bot:"):
            assert needle not in text

    def test_the_slim_document_stays_short(self, tmp_path, sources):
        assert len(document.render(strict(tmp_path), sources).splitlines()) < 60


class TestSize:
    @pytest.mark.parametrize(
        "value, shown",
        [
            (0, "0 B"),
            (1023, "1023 B"),
            (12 * 1024, "12 KiB"),
            (268435456, "256 MiB"),
            (43253760, "41.2 MiB"),
            (3 * 1024**3 // 2, "1.5 GiB"),
            (5 * 1024**4, "5 TiB"),
        ],
    )
    def test_binary_units(self, value, shown):
        assert document.size(value) == shown


class TestWrite:
    def test_the_folder_is_made_and_the_file_replaced_whole(self, tmp_path):
        target = tmp_path / "home" / ".kt-sandbox" / "about.md"
        document.write("first\n", target)
        document.write("second\n", target)
        assert target.read_text(encoding="utf-8") == "second\n"
        assert [p.name for p in target.parent.iterdir()] == ["about.md"]

    def test_a_failed_replace_leaves_no_temporary_file(self, tmp_path):
        target = tmp_path / "about.md"
        target.mkdir()
        with pytest.raises(OSError):
            document.write("text\n", target)
        assert [p.name for p in tmp_path.iterdir()] == ["about.md"]


class TestPublish:
    def test_a_managed_server_writes_the_document(self, tmp_path, sources):
        target = tmp_path / "about.md"
        written = document.publish(strict(tmp_path), target, sources)
        assert written == target
        assert "- Level: strict" in target.read_text(encoding="utf-8")

    def test_the_default_place_is_the_users_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        assert document.default_path() == tmp_path / ".kt-sandbox" / "about.md"

    def test_a_server_started_by_hand_writes_nothing(self, tmp_path, sources):
        target = tmp_path / "about.md"
        assert document.publish(ServerSettings(tmp_path), target, sources) is None
        assert not target.exists()

    def test_a_failure_is_logged_and_returns_none(self, tmp_path, sources, caplog):
        blocker = write(tmp_path / "file", "a file where a folder should be\n")
        with caplog.at_level(logging.WARNING, logger="kt_sandbox.server.about"):
            written = document.publish(strict(tmp_path), blocker / "about.md", sources)
        assert written is None
        assert "could not write" in caplog.text and str(blocker) in caplog.text
