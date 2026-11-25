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
