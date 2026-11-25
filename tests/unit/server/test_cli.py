"""Unit tests for :mod:`kt_sandbox.server.cli`."""

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from kt_sandbox import __version__
from kt_sandbox.server.app import SandboxServer
from kt_sandbox.server.cli import TOKEN_ENV, BearerAuth, build_parser, main


class TestParser:
    def test_defaults_to_stdio(self):
        args = build_parser().parse_args([])
        assert (
            args.transport == "stdio"
            and args.port == 8765
            and args.token_env == TOKEN_ENV
        )

    def test_the_name_flag_is_optional(self):
        assert build_parser().parse_args([]).name is None
        assert build_parser().parse_args(["--name", "lab"]).name == "lab"

    def test_version(self, capsys):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--version"])
        assert __version__ in capsys.readouterr().out


class TestMain:
    def test_http_without_a_token_refuses_to_start(self, monkeypatch, capsys):
        monkeypatch.delenv(TOKEN_ENV, raising=False)
        assert main(["--transport", "http"]) == 2
        err = capsys.readouterr().err
        assert f"${TOKEN_ENV}" in err and "--insecure-no-auth" in err

    def test_a_bad_limit_in_the_environment_is_reported(self, monkeypatch, capsys):
        monkeypatch.setenv("KT_SANDBOX_WALL_S", "soon")
        assert main([]) == 2
        assert "KT_SANDBOX_WALL_S" in capsys.readouterr().err


class TestNameFlag:
    @pytest.fixture
    def served(self, monkeypatch, tmp_path):
        built = []

        async def serve(self):
            built.append(self)

        monkeypatch.setattr(SandboxServer, "run_stdio", serve)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("KT_SANDBOX_WORKDIR", str(tmp_path))
        monkeypatch.delenv("KT_SANDBOX_NAME", raising=False)
        return built

    def test_a_hand_started_server_can_be_named_on_the_command_line(self, served):
        assert main(["--name", " lab "]) == 0
        text = served[0].server.instructions
        assert "the sandbox lab" in text and "`sandbox:lab/<path>`" in text

    def test_the_flag_overrides_the_environment(self, served, monkeypatch):
        monkeypatch.setenv("KT_SANDBOX_NAME", "env-name")
        assert main(["--name", "flag-name"]) == 0
        assert "sandbox:flag-name/" in served[0].server.instructions

    def test_without_a_name_there_is_no_handle(self, served):
        assert main([]) == 0
        assert "`sandbox:" not in served[0].server.instructions


class TestAboutFile:
    @pytest.fixture
    def served(self, monkeypatch, tmp_path):
        """Run ``main`` with stdio serving replaced; return the servers it built."""
        built = []

        async def serve(self):
            built.append(self)

        monkeypatch.setattr(SandboxServer, "run_stdio", serve)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("KT_SANDBOX_WORKDIR", str(tmp_path))
        return built

    def test_a_managed_server_writes_the_file_and_names_it(
        self, served, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("KT_SANDBOX_LEVEL", "strict")
        monkeypatch.setenv("KT_SANDBOX_NETWORK", "none")
        assert main([]) == 0
        about = tmp_path / "home" / ".kt-sandbox" / "about.md"
        assert "- Level: strict" in about.read_text(encoding="utf-8")
        text = served[0].server.create_initialization_options().instructions
        assert f"{about} (written when this server started)" in text

    def test_a_failed_write_still_serves_and_points_at_the_command(
        self, served, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("KT_SANDBOX_LEVEL", "strict")
        (tmp_path / "home").write_text("not a folder", encoding="utf-8")
        assert main([]) == 0
        text = served[0].server.create_initialization_options().instructions
        assert ".kt-sandbox/about.md" not in text
        assert text.endswith(
            "Run `kt-sandbox-about` for the programs, Python packages and live usage of this sandbox."
        )

    def test_a_server_started_by_hand_writes_no_file(
        self, served, monkeypatch, tmp_path
    ):
        for variable in ("KT_SANDBOX_LEVEL", "KT_SANDBOX_NETWORK", "KT_SANDBOX_SUDO"):
            monkeypatch.delenv(variable, raising=False)
        assert main([]) == 0
        assert not (tmp_path / "home").exists() and len(served) == 1

    def test_http_without_a_token_writes_nothing(self, served, monkeypatch, tmp_path):
        monkeypatch.setenv("KT_SANDBOX_LEVEL", "strict")
        monkeypatch.delenv(TOKEN_ENV, raising=False)
        assert main(["--transport", "http"]) == 2
        assert not (tmp_path / "home").exists()


class TestBearerAuth:
    @pytest.fixture
    def client(self):
        async def home(request):
            return PlainTextResponse("in")

        return TestClient(BearerAuth(Starlette(routes=[Route("/", home)]), "tok"))

    def test_the_right_token_passes(self, client):
        assert client.get("/", headers={"Authorization": "Bearer tok"}).text == "in"

    def test_a_missing_or_wrong_token_is_401_with_the_header_to_send(self, client):
        for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "tok"}):
            response = client.get("/", headers=headers)
            assert response.status_code == 401
            assert response.headers["www-authenticate"] == "Bearer"
            assert "Authorization: Bearer" in response.text
