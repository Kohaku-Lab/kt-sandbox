"""``kt-sandbox-mcp``: serve the sandbox tools over stdio or streamable HTTP."""

import argparse
import asyncio
import hmac
import os
import sys
from collections.abc import Sequence

import uvicorn
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from kt_sandbox import __version__
from kt_sandbox.server.app import SandboxServer
from kt_sandbox.server.settings import ServerSettings

DEFAULT_PORT = 8765
TOKEN_ENV = "KT_SANDBOX_MCP_TOKEN"


class BearerAuth:
    """ASGI middleware that answers 401 unless the request carries the bearer token."""

    def __init__(self, app: ASGIApp, token: str):
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            sent = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(sent, self.expected):
                response = PlainTextResponse(
                    "send the sandbox token as 'Authorization: Bearer <token>'",
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of ``kt-sandbox-mcp``."""
    parser = argparse.ArgumentParser(
        prog="kt-sandbox-mcp", description="MCP server for one sandbox."
    )
    parser.add_argument(
        "--version", action="version", version=f"kt-sandbox {__version__}"
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="stdio (default) for `docker exec -i`, http for a published port",
    )
    parser.add_argument("--host", default="0.0.0.0", help="http: address to bind")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="http: port to bind"
    )
    parser.add_argument(
        "--token-env",
        default=TOKEN_ENV,
        help=f"http: environment variable holding the bearer token (default {TOKEN_ENV})",
    )
    parser.add_argument(
        "--insecure-no-auth",
        action="store_true",
        help="http: serve without a token (anyone who reaches the port can run code)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Serve until the client disconnects (stdio) or the process is stopped (http)."""
    args = build_parser().parse_args(argv)
    try:
        settings = ServerSettings.from_env()
    except ValueError as exc:
        print(f"kt-sandbox-mcp: {exc}", file=sys.stderr)
        return 2
    server = SandboxServer(settings)
    if args.transport == "stdio":
        asyncio.run(server.run_stdio())
        return 0
    token = os.environ.get(args.token_env, "")
    if not token and not args.insecure_no_auth:
        print(
            f"kt-sandbox-mcp: http needs a token in ${args.token_env} "
            "(or --insecure-no-auth for a port nobody else can reach)",
            file=sys.stderr,
        )
        return 2
    app = server.http_app(args.host)
    uvicorn.run(
        BearerAuth(app, token) if token else app, host=args.host, port=args.port
    )
    return 0
