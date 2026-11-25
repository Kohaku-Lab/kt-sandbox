"""Unit tests for :mod:`kt_sandbox.server.tools.runner` (real subprocesses, no mocks)."""

import asyncio
import time

from kt_sandbox.server import KT_LOG_HOME
from kt_sandbox.server.tools.runner import Capture, SubprocessRunner, cap_text


def sh(command, *, wall_s=10, output_bytes=4096, **kwargs):
    kwargs.setdefault("cwd", ".")
    runner = SubprocessRunner(wall_s, output_bytes)
    return runner.run_subprocess_exec(["/bin/sh", "-c", command], **kwargs)


class TestCapture:
    def test_short_output_is_kept_whole(self):
        capture = Capture(100)
        capture.feed(b"hello ")
        capture.feed(b"world")
        assert capture.data() == b"hello world" and capture.omitted == 0

    def test_long_output_keeps_start_and_end(self):
        capture = Capture(30)
        for chunk in (b"A" * 25, b"B" * 25, b"C" * 25):
            capture.feed(chunk)
        data = capture.data()
        assert data.startswith(b"A" * 20) and data.endswith(b"C" * 10)
        assert b"B" not in data
        assert capture.omitted == 75 - 30
        assert f"{capture.omitted} bytes omitted".encode() in data

    def test_memory_stays_bounded(self):
        capture = Capture(1000)
        for _ in range(1000):
            capture.feed(b"x" * 1000)
        assert len(capture.head) + len(capture.tail) <= 1000
        assert capture.total == 1_000_000


class TestCapText:
    def test_text_within_the_limit_is_unchanged(self):
        assert cap_text("héllo", 6) == "héllo"

    def test_long_text_keeps_two_thirds_and_one_third_with_the_marker(self):
        text = cap_text("a" * 200 + "z" * 700 + "c" * 100, 300)
        assert text.startswith("a" * 200) and text.endswith("c" * 100)
        assert "[... 700 bytes omitted ...]" in text and "z" not in text


class TestRunner:
    async def test_output_is_interleaved_and_the_exit_code_kept(self):
        result = await sh("echo out; echo err >&2; echo again; exit 3")
        assert result["stdout"] == b"out\nerr\nagain\n" and result["stderr"] == b""
        assert result["returncode"] == 3 and result["timed_out"] is False

    async def test_the_command_reads_no_stdin(self):
        started = time.monotonic()
        result = await sh("cat; echo read-nothing")
        assert result["stdout"] == b"read-nothing\n"
        assert time.monotonic() - started < 2

    async def test_runs_in_the_given_folder_with_the_given_environment(self, tmp_path):
        result = await sh(
            "pwd; echo $GREETING", cwd=str(tmp_path), env={"GREETING": "hi"}
        )
        assert result["stdout"].decode().split() == [str(tmp_path.resolve()), "hi"]

    async def test_the_servers_own_kt_config_folder_stays_out_of_commands(self):
        script = "echo ${KT_CONFIG_DIR-unset}"
        ours = await sh(script, env={"KT_CONFIG_DIR": KT_LOG_HOME})
        theirs = await sh(script, env={"KT_CONFIG_DIR": "/home/me/.kt"})
        assert (ours["stdout"], theirs["stdout"]) == (b"unset\n", b"/home/me/.kt\n")

    async def test_timeout_kills_the_whole_process_group(self, tmp_path):
        marker = tmp_path / "survived"
        started = time.monotonic()
        result = await sh(f"(sleep 3; touch {marker}) & sleep 30", timeout=0.5)
        assert result["timed_out"] is True and result["returncode"] is None
        assert time.monotonic() - started < 5
        await asyncio.sleep(3.5)
        assert not marker.exists(), "the background child must die with the group"

    async def test_the_wall_cap_holds_without_a_timeout_and_over_a_longer_one(self):
        for timeout in (None, 0, 100):
            started = time.monotonic()
            result = await sh("exec sleep 30", wall_s=0.5, timeout=timeout)
            assert result["timed_out"] is True, timeout
            assert time.monotonic() - started < 4

    async def test_runaway_output_is_capped(self):
        result = await sh("yes x | head -c 5000000", max_output_bytes=3000)
        assert b"bytes omitted" in result["stdout"]
        assert len(result["stdout"]) < 3100
        assert result["stdout"].startswith(b"x\nx\n")

    async def test_the_runner_cap_applies_when_the_tool_sets_none(self):
        result = await sh("yes x | head -c 100000", output_bytes=600)
        assert len(result["stdout"]) < 700 and b"bytes omitted" in result["stdout"]

    async def test_a_background_process_does_not_hold_up_the_result(self):
        runner = SubprocessRunner(10, 4096)
        started = time.monotonic()
        result = await runner.run_subprocess_exec(
            ["/bin/sh", "-c", "(sleep 2; echo late) & echo done"], cwd="."
        )
        assert result["stdout"].strip() == b"done" and result["returncode"] == 0
        assert time.monotonic() - started < 1.5
        assert len(runner.lingering) == 1, "its output is still being read"
        await asyncio.sleep(2.5)
        assert runner.lingering == set(), "released once the background job ends"

    async def test_close_releases_what_background_jobs_hold(self):
        runner = SubprocessRunner(10, 4096)
        await runner.run_subprocess_exec(
            ["/bin/sh", "-c", "(sleep 1; echo late) & echo done"], cwd="."
        )
        (transport,) = runner.lingering
        runner.close()
        assert runner.lingering == set() and transport.is_closing()
        await asyncio.sleep(1.3)

    async def test_a_noisy_background_process_keeps_running(self, tmp_path):
        marker = tmp_path / "finished"
        await sh(
            f"(i=0; while [ $i -lt 3000 ]; do echo line-$i-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx; "
            f"i=$((i+1)); done; touch {marker}) & echo started"
        )
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        assert marker.exists(), "output nobody reads must not block the background job"
