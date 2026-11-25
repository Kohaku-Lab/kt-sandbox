"""Unit tests for :mod:`kt_sandbox.server.app`."""

from pathlib import Path

import pytest

from kt_sandbox.levels.presets import build_level
from kt_sandbox.manager.options import policy_environment
from kt_sandbox.server.app import SandboxServer, instructions
from kt_sandbox.server.settings import ServerSettings

ABOUT = Path("/home/sandbox/.kt-sandbox/about.md")


def at_level(level_name: str, name: str = "lab", **overrides) -> ServerSettings:
    """Settings as the manager sets them for a sandbox at ``level_name``."""
    level = build_level(level_name, overrides)
    return ServerSettings.from_env(
        {
            "KT_SANDBOX_WORKDIR": "/work",
            "KT_SANDBOX_NAME": name,
            "KT_SANDBOX_WALL_S": str(level.limits.wall_s),
            **policy_environment(level_name, level),
        }
    )


class TestInstructions:
    def test_a_named_sandbox_gives_the_file_handle(self):
        text = instructions(ServerSettings(Path("/work"), name="lab"))
        assert text.startswith("You work inside the sandbox lab:")
        assert "in /work" in text and "`sandbox:lab/<path>`" in text
        assert "a tool without sandbox support says so" in text

    def test_without_a_name_there_is_no_handle(self):
        text = instructions(ServerSettings(Path("/work")))
        assert text.startswith("You work inside a sandbox:")
        assert "`sandbox:" not in text and "stay between calls" in text

    def test_a_server_started_by_hand_says_only_where_it_works(self):
        for name in ("", "lab"):
            settings = ServerSettings(Path("/work"), name=name)
            text = instructions(settings, ABOUT)
            assert "Level" not in text and "kt-sandbox-about" not in text
            assert str(ABOUT) not in text and "\n" not in text

    def test_strict(self):
        text = instructions(at_level("strict"), ABOUT)
        lines = text.splitlines()
        assert lines[0].startswith("You work inside the sandbox lab:")
        assert lines[1] == (
            "Level strict: the sandbox is offline; work with the files and "
            "packages already here. Commands run as the user `sandbox`, without "
            "sudo. Each command runs up to 15 s."
        )
        assert lines[2] == (
            f"Programs, Python packages and live usage: {ABOUT} (written when "
            "this server started), or run `kt-sandbox-about` for a fresh view."
        )

    def test_standard_names_its_hosts_and_how_to_install(self):
        policy = instructions(at_level("standard"), ABOUT).splitlines()[1]
        assert policy == (
            "Level standard: the network reaches only pypi.org, "
            "files.pythonhosted.org, github.com, raw.githubusercontent.com, through "
            "a proxy already set up. Commands run as the user `sandbox`, without "
            "sudo; `pip install` installs into its home. Each command runs up to 60 s."
        )

    def test_open(self):
        policy = instructions(at_level("open"), ABOUT).splitlines()[1]
        assert policy == (
            "Level open: the network is open. `sudo` works without a password. "
            "Each command runs up to 300 s."
        )

    def test_overrides_change_the_facts(self):
        policy = instructions(
            at_level("strict", network="open", limits={"wall_s": 42})
        ).splitlines()[1]
        assert "the network is open" in policy and "up to 42 s" in policy
        assert "`pip install` installs into its home" in policy

    def test_without_a_name_the_policy_is_still_given(self):
        lines = instructions(at_level("strict", name=""), ABOUT).splitlines()
        assert lines[0].startswith("You work inside a sandbox:")
        assert lines[1].startswith("Level strict:")

    def test_without_the_file_it_points_at_the_command(self):
        last = instructions(at_level("strict")).splitlines()[-1]
        assert last == (
            "Run `kt-sandbox-about` for the programs, Python packages and live "
            "usage of this sandbox."
        )

    @pytest.mark.parametrize(
        "env, policy",
        [
            (
                {"KT_SANDBOX_SUDO": "0"},
                "Commands run as the user `sandbox`, without sudo. Each command runs up to 30 s.",
            ),
            (
                {"KT_SANDBOX_NETWORK": "none"},
                "The sandbox is offline; work with the files and packages already here. Each command runs up to 30 s.",
            ),
            (
                {"KT_SANDBOX_LEVEL": "custom"},
                "Level custom: each command runs up to 30 s.",
            ),
        ],
    )
    def test_only_the_known_facts_are_given(self, env, policy):
        settings = ServerSettings.from_env({"KT_SANDBOX_WORKDIR": "/work", **env})
        assert instructions(settings).splitlines()[1] == policy

    def test_an_allowlist_without_hosts_names_no_empty_list(self):
        settings = ServerSettings.from_env({"KT_SANDBOX_NETWORK": "allowlist"})
        policy = instructions(settings).splitlines()[1]
        assert policy.startswith(
            "The network reaches only the allowed hosts, through a proxy already set up."
        )

    def test_the_policy_is_short(self):
        for level in ("open", "standard", "strict"):
            lines = instructions(at_level(level), ABOUT).splitlines()
            assert len(" ".join(lines[1:]).split()) <= 70, level


class TestSandboxServer:
    def test_each_client_session_has_its_own_read_history(self, tmp_path):
        server = SandboxServer(ServerSettings(tmp_path))

        class Session:
            pass

        first, second = Session(), Session()
        assert server.read_state(first) is server.read_state(first)
        assert server.read_state(first) is not server.read_state(second)
        del first
        assert len(server._read_states) == 1

    def test_the_server_carries_its_instructions(self, tmp_path):
        server = SandboxServer(ServerSettings(tmp_path, name="lab"))
        options = server.server.create_initialization_options()
        assert options.instructions == instructions(server.settings)

    def test_the_instructions_name_the_about_file_it_was_given(self, tmp_path):
        server = SandboxServer(at_level("strict"), about_file=tmp_path / "about.md")
        options = server.server.create_initialization_options()
        assert f"{tmp_path / 'about.md'} (written when" in options.instructions
