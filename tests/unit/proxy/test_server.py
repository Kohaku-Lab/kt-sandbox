"""The egress proxy end to end: real sockets, a local upstream, real client connections."""

import asyncio
import base64

import pytest

from kt_sandbox.proxy.policy import Entry, Policy
from kt_sandbox.proxy.server import EgressProxy, connect_any


def basic(name, secret):
    return "Basic " + base64.b64encode(f"{name}:{secret}".encode()).decode()


class Upstream:
    """A loopback server that records what it receives and answers a canned response."""

    def __init__(self):
        self.received = []
        self.server = None

    async def start(self):
        self.server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def _serve(self, reader, writer):
        data = await reader.read(65536)
        self.received.append(data)
        if data.startswith((b"GET", b"POST")):
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nhello"
            )
        else:
            writer.write(b"echo:" + data)
        await writer.drain()
        writer.close()

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()


@pytest.fixture
async def world():
    upstream = Upstream()
    port = await upstream.start()
    policy = Policy(allow_private=True, ports=frozenset({port}))
    policy.set_entries(
        [Entry("bot", "s3cret", ("localhost",)), Entry("other", "x", ("example.org",))]
    )
    proxy = EgressProxy(policy, max_bytes=1000)
    server = await asyncio.start_server(proxy.handle, "127.0.0.1", 0)
    proxy_port = server.sockets[0].getsockname()[1]
    yield proxy_port, port, upstream
    server.close()
    await server.wait_closed()
    await upstream.stop()


async def exchange(proxy_port, request: bytes, *, then: bytes | None = None) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
    writer.write(request)
    await writer.drain()
    out = b""
    if then is not None:
        out += await reader.readuntil(b"\r\n\r\n")
        writer.write(then)
        await writer.drain()
    out += await asyncio.wait_for(reader.read(), 5)
    writer.close()
    return out


def connect(port, name="bot", secret="s3cret", host="localhost"):
    auth = f"Proxy-Authorization: {basic(name, secret)}\r\n" if name else ""
    return (
        f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n{auth}\r\n".encode()
    )


class TestConnect:
    async def test_an_allowed_host_gets_a_tunnel_that_carries_bytes(self, world):
        proxy_port, port, upstream = world
        out = await exchange(proxy_port, connect(port), then=b"ping")
        assert out.startswith(b"HTTP/1.1 200 Connection established") and out.endswith(
            b"echo:ping"
        )
        assert upstream.received == [b"ping"]

    async def test_no_credential_is_407_with_the_challenge(self, world):
        proxy_port, port, _ = world
        out = await exchange(proxy_port, connect(port, name=None))
        assert out.startswith(b"HTTP/1.1 407") and b"Proxy-Authenticate: Basic" in out

    async def test_a_wrong_secret_is_407(self, world):
        proxy_port, port, _ = world
        assert (await exchange(proxy_port, connect(port, secret="nope"))).startswith(
            b"HTTP/1.1 407"
        )

    async def test_a_host_outside_the_sandbox_allowlist_is_403_and_says_which_hosts(
        self, world
    ):
        proxy_port, port, upstream = world
        out = await exchange(proxy_port, connect(port, host="example.org"))
        assert out.startswith(b"HTTP/1.1 403") and b"allowlist: localhost" in out
        assert upstream.received == []

    async def test_one_sandbox_cannot_borrow_anothers_hosts(self, world):
        proxy_port, port, _ = world
        out = await exchange(
            proxy_port, connect(port, name="other", secret="x", host="localhost")
        )
        assert out.startswith(b"HTTP/1.1 403")

    async def test_a_port_outside_the_list_is_403(self, world):
        proxy_port, port, _ = world
        assert (await exchange(proxy_port, connect(port + 1))).startswith(
            b"HTTP/1.1 403"
        )

    async def test_a_private_target_is_refused_when_the_block_is_on(self):
        policy = Policy(ports=frozenset({9}))
        policy.set_entries([Entry("bot", "s3cret", ("localhost",))])
        server = await asyncio.start_server(EgressProxy(policy).handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        out = await exchange(port, connect(9))
        server.close()
        assert out.startswith(b"HTTP/1.1 403") and b"non-public address" in out

    async def test_the_byte_budget_ends_a_tunnel(self, world):
        proxy_port, port, _ = world
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(connect(port))
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"x" * 5000)
        await writer.drain()
        rest = await asyncio.wait_for(reader.read(), 5)
        writer.close()
        assert len(rest) < 5000

    async def test_garbage_is_400(self, world):
        proxy_port, _, _ = world
        assert (await exchange(proxy_port, b"hello\r\n\r\n")).startswith(
            b"HTTP/1.1 400"
        )


class TestPlainHttp:
    async def test_a_request_is_forwarded_without_the_proxy_headers(self, world):
        proxy_port, port, upstream = world
        request = (
            f"GET http://localhost:{port}/a/b?x=1 HTTP/1.1\r\nHost: localhost:{port}\r\n"
            f"Proxy-Authorization: {basic('bot', 's3cret')}\r\nProxy-Connection: keep-alive\r\n"
            "User-Agent: test\r\n\r\n"
        ).encode()
        out = await exchange(proxy_port, request)
        assert out.endswith(b"hello") and out.startswith(b"HTTP/1.1 200 OK")
        seen = upstream.received[0].decode()
        assert seen.startswith("GET /a/b?x=1 HTTP/1.1\r\n")
        assert "User-Agent: test" in seen and "Connection: close" in seen
        assert (
            "proxy-authorization" not in seen.lower()
            and "proxy-connection" not in seen.lower()
        )

    async def test_an_https_url_in_plain_form_is_400(self, world):
        proxy_port, port, _ = world
        request = f"GET https://localhost:{port}/ HTTP/1.1\r\nProxy-Authorization: {basic('bot', 's3cret')}\r\n\r\n".encode()
        assert (await exchange(proxy_port, request)).startswith(b"HTTP/1.1 400")

    async def test_a_forbidden_host_is_403(self, world):
        proxy_port, port, _ = world
        request = f"GET http://example.org:{port}/ HTTP/1.1\r\nProxy-Authorization: {basic('bot', 's3cret')}\r\n\r\n".encode()
        assert (await exchange(proxy_port, request)).startswith(b"HTTP/1.1 403")


class TestConnectAny:
    async def test_it_falls_through_to_the_next_address(self, world):
        _, port, _ = world
        reader, writer = await connect_any(["::1", "127.0.0.1"], port, "localhost")
        writer.close()
        assert reader is not None

    async def test_when_nothing_answers_it_says_why(self):
        from kt_sandbox.proxy.policy import Denied

        with pytest.raises(Denied, match="cannot reach localhost:9") as denied:
            await connect_any(["127.0.0.1"], 9, "localhost")
        assert denied.value.status == 502
