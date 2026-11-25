"""Unit tests for :mod:`kt_sandbox.server.cli`."""

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from kt_sandbox import __version__
from kt_sandbox.server.cli import TOKEN_ENV, BearerAuth, build_parser, main


class TestParser:
    def test_defaults_to_stdio(self):
        args = build_parser().parse_args([])
        assert (
            args.transport == "stdio"
            and args.port == 8765
            and args.token_env == TOKEN_ENV
        )

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
