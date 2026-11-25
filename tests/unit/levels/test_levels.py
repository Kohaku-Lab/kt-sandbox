"""Unit tests for :mod:`kt_sandbox.levels`."""

import pytest
from pydantic import ValidationError

from kt_sandbox.errors import LevelError
from kt_sandbox.levels.models import Level
from kt_sandbox.levels.presets import DEFAULT_ALLOW, LEVELS, build_level


class TestLevel:
    def test_the_default_level_is_the_most_closed(self):
        level = Level()
        assert level.network == "none" and level.sudo is False
        assert level.read_only is False and level.runtime == ""

    def test_allowlist_needs_hosts(self):
        with pytest.raises(ValidationError, match="at least one host"):
            Level(network="allowlist")

    def test_hosts_without_allowlist_are_refused(self):
        with pytest.raises(ValidationError, match="only used with network 'allowlist'"):
            Level(network="open", allow=["pypi.org"])

    def test_unknown_field_is_refused(self):
        with pytest.raises(ValidationError):
            Level(netwrok="open")


class TestBuildLevel:
    def test_the_three_levels_go_from_open_to_closed(self):
        open_, standard, strict = (
            build_level(n) for n in ("open", "standard", "strict")
        )
        assert (open_.network, standard.network, strict.network) == (
            "open",
            "allowlist",
            "none",
        )
        assert open_.sudo is True and standard.sudo is False and strict.sudo is False
        assert standard.allow == DEFAULT_ALLOW
        assert strict.limits.wall_s < standard.limits.wall_s < open_.limits.wall_s

    def test_limits_merge_field_by_field(self):
        level = build_level("standard", {"limits": {"memory": "4g"}})
        assert level.limits.memory == "4g" and level.limits.wall_s == 60

    def test_other_fields_replace_the_preset(self):
        assert build_level("standard", {"allow": ["example.org"]}).allow == [
            "example.org"
        ]
        assert build_level("strict", {"runtime": "my-runtime"}).runtime == "my-runtime"

    def test_leaving_allowlist_drops_the_hosts(self):
        level = build_level("standard", {"network": "none"})
        assert level.network == "none" and level.allow == []

    def test_presets_survive_building(self):
        build_level("standard", {"allow": ["example.org"], "limits": {"memory": "9g"}})
        assert LEVELS["standard"]["allow"] == DEFAULT_ALLOW
        assert LEVELS["standard"]["limits"]["memory"] == "1g"

    def test_unknown_level_names_the_choices(self):
        with pytest.raises(LevelError, match="strict"):
            build_level("yolo")

    def test_invalid_overrides_raise_level_error(self):
        with pytest.raises(LevelError):
            build_level("strict", {"network": "allowlist"})
