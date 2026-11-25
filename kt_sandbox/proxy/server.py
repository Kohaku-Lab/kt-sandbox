"""The forward proxy: CONNECT tunnels and plain HTTP, gated by the policy, with byte caps."""

import asyncio
import logging
from urllib.parse import urlsplit

from kt_sandbox.proxy.policy import Denied, Policy, split_target

LOG = logging.getLogger("kt_sandbox.proxy")
MAX_HEAD_BYTES = 16 * 1024
HEAD_TIMEOUT_S = 15
CONNECT_TIMEOUT_S = 10
IDLE_TIMEOUT_S = 120
DEFAULT_MAX_BYTES = 512 * 1024 * 1024
CHUNK_BYTES = 65536
STATUS_TEXT = {
    403: "Forbidden",
    407: "Proxy Authentication Required",
    400: "Bad Request",
    502: "Bad Gateway",
}


async def read_head(
    reader: asyncio.StreamReader,
) -> tuple[str, str, list[tuple[str, str]]] | None:
    """Read a request head: return ``(method, target, header pairs)`` as sent, or None."""
    try:
        raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEAD_TIMEOUT_S)
    except (
        asyncio.IncompleteReadError,
        asyncio.LimitOverrunError,
        asyncio.TimeoutError,
    ):
        return None
    lines = raw[:-4].decode("latin-1").split("\r\n")
    parts = lines[0].split(" ")
    if len(parts) != 3:
        return None
    headers = []
    for line in lines[1:]:
        name, sep, value = line.partition(":")
        if sep:
            headers.append((name.strip(), value.strip()))
    return parts[0], parts[1], headers


async def reply(
    writer: asyncio.StreamWriter, status: int, message: str, *, auth: bool = False
) -> None:
    """Send an error response whose body says why, so the agent can act on it."""
    body = (message + "\n").encode("utf-8")
    head = f"HTTP/1.1 {status} {STATUS_TEXT.get(status, 'Error')}\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: {len(body)}\r\nConnection: close\r\n"
    if auth:
        head += 'Proxy-Authenticate: Basic realm="kt-sandbox"\r\n'
    writer.write(head.encode("latin-1") + b"\r\n" + body)
    await writer.drain()


async def connect_any(
    addresses: list[str], port: int, host: str
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Connect to the first of ``addresses`` that answers, trying each in order."""
    failure = "no address answered"
    for address in addresses:
        try:
            return await asyncio.wait_for(
                asyncio.open_connection(address, port), CONNECT_TIMEOUT_S
            )
        except (OSError, asyncio.TimeoutError) as exc:
            failure = str(exc) or "timed out"
    raise Denied(502, f"cannot reach {host}:{port}: {failure}")


async def _copy(
    source: asyncio.StreamReader, target: asyncio.StreamWriter, budget: list[int]
) -> None:
    try:
        while chunk := await asyncio.wait_for(source.read(CHUNK_BYTES), IDLE_TIMEOUT_S):
            budget[0] -= len(chunk)
            if budget[0] < 0:
                return
            target.write(chunk)
            await target.drain()
    except (asyncio.TimeoutError, ConnectionError, OSError):
        return
    finally:
        try:
            target.close()
        except OSError:
            pass


async def tunnel(
    client_r: asyncio.StreamReader,
    client_w: asyncio.StreamWriter,
    up_r: asyncio.StreamReader,
    up_w: asyncio.StreamWriter,
    max_bytes: int,
) -> None:
    """Copy bytes both ways until either side ends or the byte budget is spent."""
    budget = [max_bytes]
    done, pending = await asyncio.wait(
        [
            asyncio.create_task(_copy(client_r, up_w, budget)),
            asyncio.create_task(_copy(up_r, client_w, budget)),
        ],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    for writer in (client_w, up_w):
        writer.close()


class EgressProxy:
    """A forward proxy that serves each sandbox only the hosts its policy entry allows."""

    def __init__(self, policy: Policy, *, max_bytes: int = DEFAULT_MAX_BYTES):
        self.policy = policy
        self.max_bytes = max_bytes

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Serve one client connection."""
        try:
            head = await read_head(reader)
            if head is None:
                await reply(writer, 400, "send an HTTP proxy request")
                return
            method, target, headers = head
            sent = {name.lower(): value for name, value in headers}
            entry = self.policy.authenticate(sent.get("proxy-authorization"))
            if method.upper() == "CONNECT":
                host, port = split_target(target)
                prefix = b""
            else:
                url = urlsplit(target)
                if url.scheme != "http" or not url.hostname:
                    raise Denied(400, "this proxy carries http:// requests and CONNECT")
                host, port = url.hostname, url.port or 80
                path = (url.path or "/") + (f"?{url.query}" if url.query else "")
                lines = [
                    f"{method} {path} HTTP/1.1",
                    *(
                        f"{name}: {value}"
                        for name, value in headers
                        if not name.lower().startswith("proxy-")
                        and name.lower() != "connection"
                    ),
                    "Connection: close",
                ]
                prefix = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")
            addresses = await self.policy.resolve(entry, host, port)
            LOG.info("allow %s -> %s:%s", entry.name, host, port)
            up_r, up_w = await connect_any(addresses, port, host)
            if method.upper() == "CONNECT":
                writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                await writer.drain()
            else:
                up_w.write(prefix)
                await up_w.drain()
            await tunnel(reader, writer, up_r, up_w, self.max_bytes)
        except Denied as denied:
            LOG.info("deny %s: %s", denied.status, denied.reason)
            await reply(writer, denied.status, denied.reason, auth=denied.status == 407)
        except (ConnectionError, OSError):
            pass
        finally:
            try:
                writer.close()
            except OSError:
                pass


async def serve(
    policy: Policy, host: str, port: int, *, max_bytes: int = DEFAULT_MAX_BYTES
) -> None:
    """Listen on ``host:port`` and serve until cancelled."""
    proxy = EgressProxy(policy, max_bytes=max_bytes)
    server = await asyncio.start_server(proxy.handle, host, port, limit=MAX_HEAD_BYTES)
    LOG.info("egress proxy listening on %s:%s", host, port)
    async with server:
        await server.serve_forever()
