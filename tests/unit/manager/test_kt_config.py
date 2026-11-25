"""Unit tests for :mod:`kt_sandbox.manager.kt_config`, read back by KohakuTerrarium's own loader."""

import stat
from pathlib import Path

import pytest
import yaml
from kohakuterrarium.core.mcp_registry import load_global_mcp_servers

from kt_sandbox.errors import ManagerError
from kt_sandbox.manager.kt_config import registry_path, upsert


def entry(name: str = "sandbox-lab", container: str = "kt-sandbox-lab") -> dict:
    return {
        "name": name,
        "transport": "stdio",
        "command": "docker",
        "args": ["exec", "-i", container, "kt-sandbox-mcp"],
    }


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    folder = tmp_path / "kt-config" / "nested"
    monkeypatch.setenv("KT_CONFIG_DIR", str(folder))
    return folder


class TestRegistryPath:
    def test_kt_config_dir_wins(self, tmp_path):
        assert registry_path({"KT_CONFIG_DIR": str(tmp_path)}) == (
            tmp_path / "mcp_servers.yaml"
        )

    def test_the_default_is_in_the_home_folder(self):
        assert registry_path({}) == (
            Path.home() / ".kohakuterrarium" / "mcp_servers.yaml"
        )


class TestUpsert:
    def test_creates_the_folder_and_the_file_kohakuterrarium_reads(self, config_dir):
        path, replaced = upsert(entry())
        assert path == config_dir / "mcp_servers.yaml" and replaced is False
        assert load_global_mcp_servers() == [entry()]

    def test_an_entry_of_the_same_name_is_replaced_in_place(self, config_dir):
        upsert(entry("first", "a"))
        upsert(entry())
        upsert(entry("last", "b"))
        path, replaced = upsert(entry(container="kt-sandbox-lab-2"))
        assert replaced is True
        assert [s["name"] for s in load_global_mcp_servers()] == [
            "first",
            "sandbox-lab",
            "last",
        ]
        assert load_global_mcp_servers()[1]["args"][2] == "kt-sandbox-lab-2"

    def test_other_entries_and_unknown_keys_are_kept(self, config_dir):
        config_dir.mkdir(parents=True)
        others = [
            {
                "name": "search",
                "transport": "streamable_http",
                "url": "https://example.org/mcp",
                "headers": {"Authorization": "Bearer ${TOKEN}"},
                "connect_timeout": 12.5,
                "env": {},
                "custom-key": ["kept", 1, None],
            },
            {"name": "tools", "transport": "stdio", "command": "uvx", "args": ["x"]},
        ]
        (config_dir / "mcp_servers.yaml").write_text(
            yaml.safe_dump(others), encoding="utf-8"
        )
        upsert(entry())
        assert load_global_mcp_servers() == [*others, entry()]

    def test_an_empty_file_counts_as_no_entries(self, config_dir):
        config_dir.mkdir(parents=True)
        (config_dir / "mcp_servers.yaml").write_text("", encoding="utf-8")
        upsert(entry())
        assert load_global_mcp_servers() == [entry()]

    @pytest.mark.parametrize(
        "content,message",
        [
            ("- name: a\n  args: [unclosed\n", "cannot read"),
            ("mcp_servers:\n  - name: a\n", "not a list of MCP servers"),
            ("- just a string\n", "not a list of MCP servers"),
        ],
    )
    def test_a_bad_file_is_refused_and_left_alone(self, config_dir, content, message):
        config_dir.mkdir(parents=True)
        path = config_dir / "mcp_servers.yaml"
        path.write_text(content, encoding="utf-8")
        with pytest.raises(ManagerError, match=message) as raised:
            upsert(entry())
        assert "Fix or move that file" in str(raised.value)
        assert path.read_text(encoding="utf-8") == content
        assert [p.name for p in config_dir.iterdir()] == ["mcp_servers.yaml"]

    def test_the_file_keeps_its_permissions(self, config_dir):
        path, _ = upsert(entry("first", "a"))
        path.chmod(0o600)
        upsert(entry())
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert [p.name for p in config_dir.iterdir()] == ["mcp_servers.yaml"]
