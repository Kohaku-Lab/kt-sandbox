"""Unit tests for :mod:`kt_sandbox.server.settings`."""

from pathlib import Path

import pytest

from kt_sandbox.server.settings import ServerSettings


class TestFromEnv:
    def test_defaults_without_environment(self):
        settings = ServerSettings.from_env({})
        assert (settings.wall_s, settings.output_bytes, settings.name) == (
            30,
            12 * 1024,
            "",
        )
        assert isinstance(settings.workdir, Path)

    def test_every_value_can_be_set(self, tmp_path):
        settings = ServerSettings.from_env(
            {
                "KT_SANDBOX_WORKDIR": str(tmp_path),
                "KT_SANDBOX_WALL_S": "5",
                "KT_SANDBOX_OUTPUT_BYTES": "2048",
                "KT_SANDBOX_NAME": " lab ",
            }
        )
        assert settings == ServerSettings(tmp_path, 5, 2048, "lab")

    def test_blank_values_mean_the_default(self):
        assert ServerSettings.from_env({"KT_SANDBOX_WALL_S": "  "}).wall_s == 30

    @pytest.mark.parametrize("bad", ["abc", "1.5", "0", "-3"])
    def test_a_bad_number_names_the_variable(self, bad):
        with pytest.raises(ValueError, match="KT_SANDBOX_WALL_S"):
            ServerSettings.from_env({"KT_SANDBOX_WALL_S": bad})


class TestPolicy:
    def test_without_the_variables_nothing_is_known(self):
        settings = ServerSettings.from_env({})
        assert (settings.level, settings.network, settings.allow, settings.sudo) == (
            "",
            "",
            (),
            None,
        )
        assert settings.has_policy is False

    def test_the_level_values_are_read(self):
        settings = ServerSettings.from_env(
            {
                "KT_SANDBOX_LEVEL": " standard ",
                "KT_SANDBOX_NETWORK": "allowlist",
                "KT_SANDBOX_ALLOW": " pypi.org, ,github.com ,",
                "KT_SANDBOX_SUDO": "0",
            }
        )
        assert settings.level == "standard" and settings.network == "allowlist"
        assert settings.allow == ("pypi.org", "github.com")
        assert settings.sudo is False and settings.has_policy is True

    @pytest.mark.parametrize(
        "variable, value", [("KT_SANDBOX_SUDO", "1"), ("KT_SANDBOX_NETWORK", "open")]
    )
    def test_any_one_value_is_enough_to_have_a_policy(self, variable, value):
        assert ServerSettings.from_env({variable: value}).has_policy is True

    def test_sudo_one_is_true(self):
        assert ServerSettings.from_env({"KT_SANDBOX_SUDO": "1"}).sudo is True

    def test_blank_values_mean_unknown(self):
        settings = ServerSettings.from_env(
            {
                "KT_SANDBOX_LEVEL": " ",
                "KT_SANDBOX_NETWORK": "  ",
                "KT_SANDBOX_ALLOW": " , ",
                "KT_SANDBOX_SUDO": "",
            }
        )
        assert settings.has_policy is False and settings.allow == ()

    @pytest.mark.parametrize("bad", ["yes", "true", "2", "-1"])
    def test_a_bad_sudo_names_the_variable(self, bad):
        with pytest.raises(ValueError, match="KT_SANDBOX_SUDO must be 0 or 1"):
            ServerSettings.from_env({"KT_SANDBOX_SUDO": bad})

    @pytest.mark.parametrize("bad", ["offline", "Open", "all"])
    def test_a_bad_network_names_the_variable_and_the_choices(self, bad):
        with pytest.raises(
            ValueError, match="KT_SANDBOX_NETWORK.*none, allowlist, open"
        ):
            ServerSettings.from_env({"KT_SANDBOX_NETWORK": bad})
