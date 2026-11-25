"""Unit tests for :mod:`kt_sandbox.server.about.cli`."""

import subprocess
import sys

import pytest

from kt_sandbox import __version__
from kt_sandbox.server.about.cli import main

SECRETS = {
    "HTTP_PROXY": "http://lab:egress-s3cret-1@kt-sandbox-egress:3128",
    "https_proxy": "http://lab:egress-s3cret-1@kt-sandbox-egress:3128",
    "KT_SANDBOX_EGRESS_SECRET": "egress-s3cret-1",
    "KT_SANDBOX_MCP_TOKEN": "mcp-t0ken-2",
}


@pytest.fixture
def standard(monkeypatch, tmp_path):
    for key, value in {
        **SECRETS,
        "KT_SANDBOX_NAME": "lab",
        "KT_SANDBOX_LEVEL": "standard",
        "KT_SANDBOX_NETWORK": "allowlist",
        "KT_SANDBOX_ALLOW": "pypi.org,github.com",
        "KT_SANDBOX_SUDO": "0",
        "KT_SANDBOX_WALL_S": "60",
        "KT_SANDBOX_WORKDIR": str(tmp_path),
        "HOME": str(tmp_path / "home"),
    }.items():
        monkeypatch.setenv(key, value)


def test_prints_the_document_from_the_environment(standard, capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# About the sandbox lab\n")
    assert "- Level: standard" in out and "- One command: up to 60 s" in out
    assert "- Network: only pypi.org, github.com" in out


def test_no_secret_from_the_environment_is_printed(standard, capsys):
    assert main([]) == 0
    captured = capsys.readouterr()
    for needle in ("s3cret", "t0ken", "egress:3128", "lab:"):
        assert needle not in captured.out and needle not in captured.err


def test_printing_writes_no_file(standard, tmp_path):
    assert main([]) == 0
    assert not (tmp_path / "home" / ".kt-sandbox").exists()


def test_a_bad_value_is_reported_and_the_rest_still_prints(
    standard, monkeypatch, capsys
):
    monkeypatch.setenv("KT_SANDBOX_SUDO", "maybe")
    assert main([]) == 0
    captured = capsys.readouterr()
    assert "KT_SANDBOX_SUDO" in captured.err
    assert "- Level: unknown" in captured.out and "## Usage now" in captured.out


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert __version__ in capsys.readouterr().out


def test_runs_as_a_module(standard):
    done = subprocess.run(
        [sys.executable, "-m", "kt_sandbox.server.about"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert "- Level: standard" in done.stdout and "s3cret" not in done.stdout
