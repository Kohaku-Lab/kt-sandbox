"""Unit tests for :mod:`kt_sandbox.server.app`."""

from pathlib import Path

from kt_sandbox.server.app import SandboxServer, instructions
from kt_sandbox.server.settings import ServerSettings


class TestInstructions:
    def test_a_named_sandbox_gives_the_file_handle(self):
        text = instructions(ServerSettings(Path("/work"), name="lab"))
        assert text.startswith("You work inside the sandbox lab:")
        assert "in /work" in text and "`sandbox:lab/<path>`" in text

    def test_without_a_name_there_is_no_handle(self):
        text = instructions(ServerSettings(Path("/work")))
        assert text.startswith("You work inside a sandbox:")
        assert "`sandbox:" not in text and "stay between calls" in text


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
