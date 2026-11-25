"""Run the ``bash`` tool's command with a wall-time cap and bounded output.

KohakuTerrarium's ``bash`` tool hands its command to a ``subprocess_runner``
from the tool context when one is present. This runner keeps the output in
memory as a bounded head and tail, kills the whole process group at the time
limit, and returns as soon as the shell exits, even when it leaves background
processes running; their output keeps being read and dropped so they never
block on a full pipe.
"""

import asyncio
import os
import signal
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from kt_sandbox.server import KT_LOG_HOME

DRAIN_GRACE_S = 0.5


class Capture:
    """Keeps the first two thirds and the last third of ``limit`` bytes of a stream."""

    def __init__(self, limit: int):
        self.head_limit = max(limit * 2 // 3, 1)
        self.tail_limit = max(limit - self.head_limit, 1)
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0

    def feed(self, chunk: bytes) -> None:
        """Add the next chunk of output."""
        self.total += len(chunk)
        room = self.head_limit - len(self.head)
        if room > 0:
            self.head += chunk[:room]
            chunk = chunk[room:]
        if chunk:
            self.tail += chunk
            if len(self.tail) > self.tail_limit:
                del self.tail[: len(self.tail) - self.tail_limit]

    @property
    def omitted(self) -> int:
        """Bytes seen but kept in neither the head nor the tail."""
        return self.total - len(self.head) - len(self.tail)

    def data(self) -> bytes:
        """Return the kept bytes, with a marker where bytes were left out."""
        if not self.omitted:
            return bytes(self.head + self.tail)
        marker = f"\n[... {self.omitted} bytes omitted ...]\n".encode()
        return bytes(self.head) + marker + bytes(self.tail)


def cap_text(text: str, limit: int) -> str:
    """Return ``text`` cut to ``limit`` UTF-8 bytes the way :class:`Capture` cuts a stream."""
    capture = Capture(limit)
    capture.feed(text.encode("utf-8"))
    return capture.data().decode("utf-8", errors="replace")


def command_environment(env: Mapping[str, str] | None) -> dict[str, str] | None:
    """The environment a command runs with: ``env`` without the server's own KT config folder."""
    if env is None:
        return None
    return {
        key: value
        for key, value in env.items()
        if not (key == "KT_CONFIG_DIR" and value == KT_LOG_HOME)
    }


def _kill_group(pid: int | None) -> None:
    if pid is None:
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


class _Collect(asyncio.SubprocessProtocol):
    """Feeds the command's output into a :class:`Capture` and notes exit and end of output."""

    def __init__(
        self,
        capture: Capture,
        on_drained: Callable[[asyncio.SubprocessTransport], None],
    ):
        self.capture = capture
        self.exited = asyncio.Event()
        self.drained = asyncio.Event()
        self.on_drained = on_drained
        self.transport: asyncio.SubprocessTransport | None = None

    def connection_made(self, transport: asyncio.SubprocessTransport) -> None:
        self.transport = transport

    def pipe_data_received(self, fd: int, data: bytes) -> None:
        self.capture.feed(data)

    def pipe_connection_lost(self, fd: int, exc: Exception | None) -> None:
        self.drained.set()
        if self.transport is not None:
            self.on_drained(self.transport)

    def process_exited(self) -> None:
        self.exited.set()


class SubprocessRunner:
    """The ``subprocess_runner`` runtime service the ``bash`` tool runs commands through.

    ``wall_s`` caps every command, including one asked to run without a
    timeout; ``output_bytes`` caps the output kept when the tool asks for no cap.
    Call :meth:`close` before the event loop ends.
    """

    def __init__(self, wall_s: float, output_bytes: int):
        self.wall_s = wall_s
        self.output_bytes = output_bytes
        self.lingering: set[asyncio.SubprocessTransport] = set()

    async def run_subprocess_exec(
        self,
        argv: Sequence[str],
        *,
        cwd: str,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
        max_output_bytes: int | None = None,
    ) -> dict[str, Any]:
        """Run ``argv`` in its own process group; stderr is merged into stdout.

        Returns ``stdout``, ``stderr`` (always empty), ``returncode`` and
        ``timed_out``, the shape the ``bash`` tool reads. At the time limit the
        whole group is killed. The command gets no stdin, so it can never read
        the MCP stream of a stdio server.
        """
        limit = min(timeout, self.wall_s) if timeout else self.wall_s
        capture = Capture(max_output_bytes or self.output_bytes)
        transport, protocol = await asyncio.get_running_loop().subprocess_exec(
            lambda: _Collect(capture, self._release),
            *argv,
            cwd=cwd,
            env=command_environment(env),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        timed_out = False
        try:
            await asyncio.wait_for(protocol.exited.wait(), limit)
        except asyncio.TimeoutError:
            timed_out = True
            _kill_group(transport.get_pid())
            await protocol.exited.wait()
        except asyncio.CancelledError:
            _kill_group(transport.get_pid())
            transport.close()
            raise
        try:
            await asyncio.wait_for(protocol.drained.wait(), DRAIN_GRACE_S)
        except asyncio.TimeoutError:
            pass
        if protocol.drained.is_set():
            transport.close()
        else:
            self.lingering.add(transport)
        return {
            "stdout": capture.data(),
            "stderr": b"",
            "returncode": None if timed_out else transport.get_returncode(),
            "timed_out": timed_out,
        }

    def _release(self, transport: asyncio.SubprocessTransport) -> None:
        """Close a background command's transport once its output has ended."""
        if transport in self.lingering:
            self.lingering.discard(transport)
            transport.close()

    def close(self) -> None:
        """Stop reading the output of background processes that are still running."""
        while self.lingering:
            self.lingering.pop().close()
