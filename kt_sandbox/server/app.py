"""Build the MCP server: KohakuTerrarium's tools, listed with KohakuTerrarium's own schemas."""

import contextlib
import weakref
from collections.abc import AsyncIterator
from typing import Any

from kohakuterrarium.utils.file.guard import FileReadState
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from kt_sandbox import __version__
from kt_sandbox.server.settings import ServerSettings
from kt_sandbox.server.tools.catalog import Toolbox

SERVER_NAME = "kt-sandbox"
HTTP_PATH = "/mcp"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def instructions(settings: ServerSettings) -> str:
    """The text a client shows its model about this server."""
    if settings.name:
        return (
            f"You work inside the sandbox {settings.name}: these tools run there, "
            f"in {settings.workdir}, and files and packages stay between calls. A "
            "file here can be passed to any tool that takes a file or media argument "
            f"as `sandbox:{settings.name}/<path>`."
        )
    return (
        f"You work inside a sandbox: these tools run there, in {settings.workdir}, "
        "and files and packages stay between calls."
    )


class _Endpoint:
    """The ASGI app behind ``/mcp``: every request goes to the session manager."""

    def __init__(self, manager: StreamableHTTPSessionManager):
        self.manager = manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.manager.handle_request(scope, receive, send)


class SandboxServer:
    """The low-level MCP server and the per-client state of its tools.

    Each client session gets its own read history, so KohakuTerrarium's
    read-before-write rule applies to what that client has read.
    """

    def __init__(self, settings: ServerSettings):
        self.settings = settings
        self.toolbox = Toolbox(settings)
        self._read_states: weakref.WeakKeyDictionary[Any, FileReadState] = (
            weakref.WeakKeyDictionary()
        )
        self.server: Server = Server(
            SERVER_NAME, version=__version__, instructions=instructions(settings)
        )
        self.server.list_tools()(self._list_tools)
        self.server.call_tool(validate_input=True)(self._call_tool)

    async def _list_tools(self) -> list[types.Tool]:
        return self.toolbox.listing

    def read_state(self, session: Any) -> FileReadState:
        """Return the read history of one client session, creating it on first use."""
        state = self._read_states.get(session)
        if state is None:
            state = self._read_states[session] = FileReadState()
        return state

    async def _call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> types.CallToolResult:
        session = self.server.request_context.session
        return await self.toolbox.call(name, arguments, self.read_state(session))

    async def run_stdio(self) -> None:
        """Serve one client over stdin and stdout until it disconnects."""
        try:
            async with stdio_server() as (read, write):
                await self.server.run(
                    read, write, self.server.create_initialization_options()
                )
        finally:
            self.toolbox.runner.close()

    @contextlib.asynccontextmanager
    async def _http_lifespan(
        self, manager: StreamableHTTPSessionManager
    ) -> AsyncIterator[None]:
        async with manager.run():
            try:
                yield
            finally:
                self.toolbox.runner.close()

    def http_app(self, host: str) -> Starlette:
        """Return the streamable-HTTP app serving at ``/mcp``.

        Bound to a loopback address it accepts only loopback ``Host`` and
        ``Origin`` headers, against DNS rebinding.
        """
        security = None
        if host in LOCAL_HOSTS:
            security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
                allowed_origins=[
                    "http://127.0.0.1:*",
                    "http://localhost:*",
                    "http://[::1]:*",
                ],
            )
        manager = StreamableHTTPSessionManager(
            app=self.server, security_settings=security
        )
        return Starlette(
            routes=[Route(HTTP_PATH, endpoint=_Endpoint(manager))],
            lifespan=lambda app: self._http_lifespan(manager),
        )
