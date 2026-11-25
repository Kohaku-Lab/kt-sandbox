"""Unit tests for :mod:`kt_sandbox.manager.options`."""

import pytest

from kt_sandbox.errors import ManagerError
from kt_sandbox.levels.presets import build_level
from kt_sandbox.manager import options
from kt_sandbox.manager.options import (
    Mount,
    container_name,
    container_options,
    parse_mount,
    proxy_environment,
    validate_name,
)


def opts(level_name, **kwargs):
    if level_name == "standard":
        kwargs.setdefault("egress_secret", "s3cret")
    return container_options(
        "lab", level_name, build_level(level_name), image="img:1", **kwargs
    )


class TestNames:
    def test_valid_names(self):
        assert [validate_name(n) for n in ("a", "lab-1", "my_box.v2")] == [
            "a",
            "lab-1",
            "my_box.v2",
        ]
        assert container_name("lab") == "kt-sandbox-lab"

    @pytest.mark.parametrize("bad", ["", "Lab", "-x", "a b", "a/b", "x" * 41])
    def test_invalid_names_state_the_rule(self, bad):
        with pytest.raises(ManagerError, match="lowercase letters"):
            validate_name(bad)


class TestParseMount:
    def test_forms(self):
        assert parse_mount("/data:/mnt/data") == Mount("/data", "/mnt/data", False)
        assert parse_mount("/data:/mnt/data:ro") == Mount("/data", "/mnt/data", True)

    def test_a_relative_source_becomes_absolute(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert parse_mount("src:/code").source == str(tmp_path / "src")

    @pytest.mark.parametrize(
        "bad", ["/a", "/a:", ":/b", "/a:/b:rw", "/a:b", "/a:/b:ro:x"]
    )
    def test_bad_mounts_show_the_forms(self, bad):
        with pytest.raises(ManagerError, match="SOURCE:TARGET|absolute"):
            parse_mount(bad)


class TestContainerOptions:
    def test_strict_is_closed_down(self):
        o = opts("strict")
        assert opts("standard")["cap_drop"] == ["ALL"]
        assert o["network_mode"] == "none" and "network" not in o
        assert o["user"] == "sandbox" and o["cap_drop"] == ["ALL"]
        assert o["nano_cpus"] == 500_000_000
        assert o["mem_limit"] == o["memswap_limit"] == "256m"
        assert o["pids_limit"] == 64
        assert o["security_opt"] == ["no-new-privileges:true"]
        assert o["init"] is True and o["command"] == ["sleep", "infinity"]

    def test_open_allows_sudo_so_it_keeps_capabilities_and_privilege_escalation(self):
        o = opts("open")
        assert o["user"] == "sandbox"
        assert "cap_drop" not in o and "security_opt" not in o
        assert "network_mode" not in o and "network" not in o
        assert o["mem_limit"] == "2g"

    def test_allowlist_joins_its_own_internal_network_and_sets_the_proxy(self):
        o = opts("standard")
        assert o["network"] == "kt-sandbox-net-lab" and "network_mode" not in o
        env = o["environment"]
        assert env["HTTPS_PROXY"] == "http://lab:s3cret@kt-sandbox-egress:3128"
        assert env["KT_SANDBOX_EGRESS_SECRET"] == "s3cret"
        assert o["labels"]["kt-sandbox.network"] == "allowlist"
        assert "pypi.org" in o["labels"]["kt-sandbox.allow"]

    def test_an_allowlist_sandbox_without_a_credential_is_refused(self):
        with pytest.raises(ManagerError, match="egress credential"):
            container_options("lab", "standard", build_level("standard"), image="i")

    def test_other_levels_blank_the_proxy_so_a_saved_image_cannot_leak_it(self):
        for level in ("strict", "open"):
            env = opts(level)["environment"]
            assert all(env[var] == "" for var in options.PROXY_VARS), level

    def test_limits_reach_the_in_container_server(self):
        env = opts("strict")["environment"]
        assert env["KT_SANDBOX_WALL_S"] == "15"
        assert env["KT_SANDBOX_OUTPUT_BYTES"] == str(12 * 1024)
        assert env["KT_SANDBOX_WORKDIR"] == "/work"
        assert env["KT_SANDBOX_NAME"] == "lab"

    def test_labels_name_the_sandbox_level_and_whether_sudo_is_allowed(self):
        assert opts("strict")["labels"] == {
            "kt-sandbox.name": "lab",
            "kt-sandbox.level": "strict",
            "kt-sandbox.sudo": "false",
            "kt-sandbox.network": "none",
            "kt-sandbox.allow": "[]",
        }

    def test_runtime_read_only_mounts_publish_and_env(self):
        level = build_level("strict", {"runtime": "my-runtime", "read_only": True})
        o = container_options(
            "lab",
            "strict",
            level,
            image="img:1",
            mounts=(Mount("/data", "/mnt", True),),
            env={"X": "1"},
            publish=9000,
        )
        assert o["runtime"] == "my-runtime" and o["read_only"] is True
        assert set(o["tmpfs"]) == {"/tmp", "/work", "/run"}
        assert o["mounts"] == [
            {"Type": "bind", "Source": "/data", "Target": "/mnt", "ReadOnly": True}
        ]
        assert o["ports"] == {"8765/tcp": 9000} and o["environment"]["X"] == "1"

    def test_a_bad_name_is_refused_before_anything_is_built(self):
        with pytest.raises(ManagerError):
            container_options("Bad Name", "strict", build_level("strict"), image="i")


def test_proxy_environment_covers_both_cases():
    assert set(proxy_environment(build_level("open"))) == set(options.PROXY_VARS)


def test_other_levels_carry_no_credential():
    for level in ("strict", "open"):
        env = opts(level)["environment"]
        assert env["KT_SANDBOX_EGRESS_SECRET"] == ""
        assert opts(level)["labels"]["kt-sandbox.allow"] == "[]"
