"""Unit tests for :mod:`kt_sandbox.cli` (the parts that need no Docker)."""

import subprocess
import sys

import pytest

from kt_sandbox import __version__
from kt_sandbox.cli import COMMANDS, build_parser, main
from kt_sandbox.cli.up import overrides_from

NAMES = (
    "up",
    "down",
    "ls",
    "rm",
    "connect",
    "save",
    "images",
    "export",
    "import_",
    "levels",
    "mcp",
    "doctor",
    "build",
    "proxy",
)


class TestMain:
    def test_version(self, capsys):
        with pytest.raises(SystemExit) as stop:
            main(["--version"])
        assert stop.value.code == 0
        assert capsys.readouterr().out.strip() == f"kt-sandbox {__version__}"

    def test_no_command_prints_help_and_fails(self, capsys):
        assert main([]) == 2
        assert "usage: kt-sandbox" in capsys.readouterr().err

    def test_every_command_is_registered_once(self):
        names = [module.__name__.rsplit(".", 1)[-1] for module in COMMANDS]
        assert sorted(names) == sorted(NAMES)

    def test_the_proxy_command_takes_a_port_and_a_policy_file(self):
        args = build_parser().parse_args(
            ["proxy", "--port", "1234", "--policy", "p.json"]
        )
        assert (args.port, args.policy, args.host) == (1234, "p.json", "0.0.0.0")

    def test_export_and_import_are_registered_under_their_command_names(self):
        args = build_parser().parse_args(["export", "lab", "lab.tar.gz", "--force"])
        assert (args.image, args.file, args.force) == ("lab", "lab.tar.gz", True)
        assert build_parser().parse_args(["export", "lab", "x.tar"]).force is False
        assert build_parser().parse_args(["import", "lab.tar"]).file == "lab.tar"

    def test_mcp_prints_registers_or_shows_http_but_not_two_at_once(self, capsys):
        assert build_parser().parse_args(["mcp", "lab"]).register is False
        args = build_parser().parse_args(["mcp", "lab", "--register"])
        assert (args.name, args.register, args.http) == ("lab", True, False)
        with pytest.raises(SystemExit):
            build_parser().parse_args(["mcp", "lab", "--register", "--http"])
        assert "not allowed with" in capsys.readouterr().err

    def test_the_command_runs_without_the_docker_package_as_in_the_image(self):
        script = (
            "import sys; sys.modules['docker'] = None; "
            "from kt_sandbox.cli import main; sys.exit(main(['levels']))"
        )
        done = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True
        )
        assert done.returncode == 0, done.stderr
        assert "strict" in done.stdout

    def test_sandbox_errors_print_one_line_and_exit_1(self, capsys):
        assert main(["up", "Bad Name"]) == 1
        err = capsys.readouterr().err
        assert err.startswith("kt-sandbox: ") and "lowercase letters" in err


class TestLevelsCommand:
    def test_lists_the_three_levels_without_docker(self, capsys):
        assert main(["levels"]) == 0
        out = capsys.readouterr().out
        rows = {line.split()[0]: line for line in out.splitlines()[1:]}
        assert set(rows) == {"open", "standard", "strict"}
        assert "none" in rows["strict"] and "open" in rows["open"]
        assert "allowlist (4 hosts)" in rows["standard"]


class TestUpOptions:
    def parse(self, *argv):
        return build_parser().parse_args(["up", "lab", *argv])

    def test_the_level_is_left_unset_so_an_existing_sandbox_keeps_its_own(self):
        assert self.parse().level is None
        assert self.parse("--level", "strict").level == "strict"

    def test_no_flags_means_no_overrides(self):
        assert overrides_from(self.parse()) == {}

    def test_limits_and_fields_are_collected(self):
        args = self.parse(
            "--cpus",
            "2",
            "--memory",
            "3g",
            "--pids",
            "99",
            "--wall",
            "7",
            "--runtime",
            "my-runtime",
            "--read-only",
        )
        assert overrides_from(args) == {
            "runtime": "my-runtime",
            "read_only": True,
            "limits": {"cpus": 2.0, "memory": "3g", "pids": 99, "wall_s": 7},
        }

    def test_allow_implies_the_allowlist_network(self):
        args = self.parse("--allow", "example.org", "--allow", "pypi.org")
        assert overrides_from(args) == {
            "allow": ["example.org", "pypi.org"],
            "network": "allowlist",
        }

    def test_an_explicit_network_wins_over_the_implied_one(self):
        args = self.parse("--network", "open")
        assert overrides_from(args) == {"network": "open"}
