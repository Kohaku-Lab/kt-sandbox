"""Unit tests for :mod:`kt_sandbox.server.files`: the rule, the command and the HTTP route."""

import os
import subprocess
import sys

import pytest
from starlette.testclient import TestClient

from kt_sandbox.errors import BadReference, NotAFile, NotFound, TooLarge
from kt_sandbox.server import files
from kt_sandbox.server.app import SandboxServer
from kt_sandbox.server.cli import BearerAuth
from kt_sandbox.server.settings import ServerSettings

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 600
AUTH = {"Authorization": "Bearer tok"}


@pytest.fixture
def work(tmp_path):
    """A work folder with a PNG, a folder, a symlink, a FIFO and a file outside it."""
    root = tmp_path / "work"
    (root / "out").mkdir(parents=True)
    (root / "out" / "x.png").write_bytes(PNG)
    (root / "out" / "passwd").symlink_to("/etc/passwd")
    os.mkfifo(root / "out" / "pipe")
    (tmp_path / "outside.txt").write_bytes(b"outside\n")
    return root


class TestOpen:
    def test_a_relative_path_is_under_the_work_folder(self, work):
        with files.open_file("out/x.png", work) as opened:
            assert opened.path == work / "out" / "x.png"
            assert opened.size == len(PNG) and b"".join(opened.chunks()) == PNG
            assert opened.mtime == pytest.approx(
                (work / "out" / "x.png").stat().st_mtime
            )

    def test_an_absolute_path_is_used_as_given(self, work):
        outside = work.parent / "outside.txt"
        with files.open_file(str(outside), work) as opened:
            assert b"".join(opened.chunks()) == b"outside\n"

    @pytest.mark.parametrize(
        "path, error, message",
        [
            ("", BadReference, "name a file"),
            ("   ", BadReference, "name a file"),
            ("out/nope.png", NotFound, "does not exist"),
            ("out/x.png/inner", NotFound, "does not exist"),
            ("out", NotAFile, "is a folder"),
            ("out/passwd", NotAFile, "symbolic link to /etc/passwd"),
            ("out/pipe", NotAFile, "special file"),
        ],
    )
    def test_refusals(self, work, path, error, message):
        with pytest.raises(error, match=message):
            files.open_file(path, work)

    def test_a_file_over_the_limit_is_refused_before_reading(self, work):
        with pytest.raises(
            TooLarge, match=f"{len(PNG)} bytes, over the 100-byte limit"
        ):
            files.open_file("out/x.png", work, max_bytes=100)

    def test_the_limit_holds_while_streaming(self, work):
        opened = files.open_file("out/x.png", work)
        opened.limit = 1000
        with opened, pytest.raises(TooLarge):
            b"".join(opened.chunks())

    def test_a_file_that_grew_is_cut_at_its_announced_size(self, work):
        with files.open_file("out/x.png", work) as opened:
            with (work / "out" / "x.png").open("ab") as grow:
                grow.write(b"more")
            assert b"".join(opened.chunks()) == PNG


class TestLimit:
    def test_none_is_the_ceiling(self):
        assert files.limit_of(None) == files.MAX_BYTES == 64 * 1024 * 1024

    def test_a_larger_request_is_clamped(self):
        assert files.limit_of(files.MAX_BYTES * 4) == files.MAX_BYTES
        assert files.limit_of(10) == 10

    def test_a_limit_below_one_is_refused(self):
        with pytest.raises(BadReference, match="at least 1"):
            files.limit_of(0)


class TestCommand:
    def run(self, work, *args):
        env = {**os.environ, "KT_SANDBOX_WORKDIR": str(work)}
        return subprocess.run(
            [sys.executable, "-m", "kt_sandbox.server.files", *args],
            capture_output=True,
            env=env,
            check=False,
        )

    def test_writes_the_bytes(self, work):
        done = self.run(work, "out/x.png")
        assert (done.returncode, done.stdout, done.stderr) == (0, PNG, b"")

    @pytest.mark.parametrize(
        "args, code, message",
        [
            (["out/nope.png"], 3, b"does not exist"),
            (["out"], 4, b"is a folder"),
            (["out/passwd"], 4, b"symbolic link"),
            (["out/pipe"], 4, b"special file"),
            (["out/x.png", "--max-bytes", "10"], 5, b"over the 10-byte limit"),
            ([""], 2, b"name a file"),
            ([], 2, b"usage"),
            (["out/x.png", "--max-bytes", "0"], 2, b"at least 1"),
        ],
    )
    def test_errors(self, work, args, code, message):
        done = self.run(work, *args)
        assert done.returncode == code and done.stdout == b""
        assert message in done.stderr

    def test_in_process(self, work, monkeypatch, capsysbinary):
        monkeypatch.setenv("KT_SANDBOX_WORKDIR", str(work))
        assert files.main(["out/x.png"]) == 0
        assert capsysbinary.readouterr().out == PNG


class TestRoute:
    @pytest.fixture
    def client(self, work):
        server = SandboxServer(ServerSettings(work, name="lab"))
        app = BearerAuth(server.http_app("127.0.0.1"), "tok")
        with TestClient(app, base_url="http://127.0.0.1:8765") as client:
            yield client

    def get(self, client, path=None, headers=AUTH, **params):
        if path is not None:
            params["path"] = path
        return client.get("/mcp/files", params=params, headers=headers)

    def test_no_token_is_401(self, client):
        assert self.get(client, "out/x.png", headers={}).status_code == 401
        wrong = {"Authorization": "Bearer nope"}
        assert self.get(client, "out/x.png", headers=wrong).status_code == 401

    def test_the_bytes_and_headers(self, client, work):
        response = self.get(client, "out/x.png")
        assert response.status_code == 200 and response.content == PNG
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["content-length"] == str(len(PNG))
        assert response.headers["x-kt-sandbox-size"] == str(len(PNG))
        mtime = (work / "out" / "x.png").stat().st_mtime
        assert float(response.headers["x-kt-sandbox-mtime"]) == pytest.approx(mtime)

    def test_an_absolute_path(self, client, work):
        response = self.get(client, str(work.parent / "outside.txt"))
        assert response.status_code == 200 and response.content == b"outside\n"

    @pytest.mark.parametrize(
        "path, status, message",
        [
            (None, 400, "name a file"),
            ("", 400, "name a file"),
            ("out/nope.png", 404, "does not exist"),
            ("out", 422, "is a folder"),
            ("out/passwd", 422, "symbolic link to /etc/passwd"),
            ("out/pipe", 422, "special file"),
        ],
    )
    def test_errors_are_json(self, client, path, status, message):
        response = self.get(client, path)
        assert response.status_code == status
        assert message in response.json()["error"]

    def test_too_big_is_413_before_any_body(self, client):
        response = self.get(client, "out/x.png", max_bytes="100")
        assert response.status_code == 413
        error = response.json()["error"]
        assert str(len(PNG)) in error and "100-byte limit" in error

    def test_a_bad_max_bytes_is_400(self, client):
        for value in ("many", "0", "-5"):
            assert self.get(client, "out/x.png", max_bytes=value).status_code == 400

    def test_a_huge_max_bytes_is_clamped(self, client, monkeypatch):
        monkeypatch.setattr(files, "MAX_BYTES", 1000)
        response = self.get(client, "out/x.png", max_bytes=str(10**12))
        assert response.status_code == 413 and "1000-byte limit" in response.text

    def test_requests_are_logged_without_headers(self, client, caplog):
        with caplog.at_level("INFO", logger="kt_sandbox.server.files"):
            self.get(client, "out/x.png")
            self.get(client, "out/nope.png")
        text = caplog.text
        assert "out/x.png" in text and "200" in text and "404" in text
        assert "tok" not in text and "Bearer" not in text

    def test_mcp_still_answers(self, client):
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "1"},
                },
            },
            headers={**AUTH, "Accept": "application/json, text/event-stream"},
        )
        assert response.status_code == 200 and "kt-sandbox" in response.text
