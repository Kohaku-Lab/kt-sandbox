"""Who may reach what: per-sandbox credentials, host allowlists, private-address blocking."""

import asyncio
import base64
import binascii
import hmac
import ipaddress
import json
import socket
from dataclasses import dataclass
from pathlib import Path

ALLOWED_PORTS = frozenset({80, 443})


class Denied(Exception):
    """A request the proxy refuses; ``status`` is the HTTP status it answers with."""

    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


@dataclass(frozen=True)
class Entry:
    """One sandbox's credential and the hosts it may reach."""

    name: str
    secret: str
    allow: tuple[str, ...]


def host_allowed(allow: tuple[str, ...], host: str) -> bool:
    """Whether ``host`` is one of ``allow`` or a subdomain of one."""
    host = host.lower().rstrip(".")
    return any(
        host == entry or host.endswith("." + entry) for entry in map(str.lower, allow)
    )


def parse_basic(header: str | None) -> tuple[str, str] | None:
    """Return ``(name, secret)`` from a ``Proxy-Authorization: Basic ...`` value, or None."""
    if not header or not header.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    name, sep, secret = decoded.partition(":")
    return (name, secret) if sep else None


def split_target(target: str) -> tuple[str, int]:
    """Split ``host:port`` (CONNECT) or ``host`` into host and port (default 443)."""
    host, sep, port = target.rpartition(":")
    if sep and port.isdigit() and not host.endswith(":"):
        return host.strip("[]"), int(port)
    return target.strip("[]"), 443


class Policy:
    """The allowlist table, reloaded from its file whenever the file changes.

    ``allow_private`` and ``ports`` exist so tests can use a loopback upstream
    on an unprivileged port; the defaults are the real policy.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        allow_private: bool = False,
        ports: frozenset[int] = ALLOWED_PORTS,
    ):
        self.path = path
        self.allow_private = allow_private
        self.ports = ports
        self._entries: dict[str, Entry] = {}
        self._mtime: float | None = None

    def set_entries(self, entries: list[Entry]) -> None:
        """Replace the table directly (used by tests)."""
        self._entries = {entry.name: entry for entry in entries}

    def _reload(self) -> None:
        if self.path is None:
            return
        try:
            mtime = self.path.stat().st_mtime_ns
        except OSError:
            return
        if mtime == self._mtime:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self._mtime = mtime
        self.set_entries(
            [
                Entry(item["name"], item["secret"], tuple(item.get("allow", ())))
                for item in data.get("sandboxes", ())
            ]
        )

    def authenticate(self, authorization: str | None) -> Entry:
        """Return the sandbox this credential belongs to, or raise a 407."""
        self._reload()
        parsed = parse_basic(authorization)
        entry = self._entries.get(parsed[0]) if parsed else None
        if entry is None or not hmac.compare_digest(entry.secret, parsed[1]):
            raise Denied(407, "this sandbox is not known to the egress proxy")
        return entry

    async def resolve(self, entry: Entry, host: str, port: int) -> list[str]:
        """Return the public addresses of ``host`` in connection order, or raise why it is refused."""
        if port not in self.ports:
            allowed = ", ".join(map(str, sorted(self.ports)))
            raise Denied(
                403,
                f"port {port} is not allowed; the proxy only carries ports {allowed}",
            )
        if not host_allowed(entry.allow, host):
            allowed = ", ".join(entry.allow) or "(none)"
            raise Denied(
                403, f"host {host} is not in this sandbox's allowlist: {allowed}"
            )
        try:
            found = await asyncio.get_running_loop().getaddrinfo(
                host, port, type=socket.SOCK_STREAM
            )
        except socket.gaierror as exc:
            raise Denied(502, f"cannot resolve {host}: {exc}") from exc
        addresses = list(dict.fromkeys(item[4][0] for item in found))
        if not addresses:
            raise Denied(502, f"{host} has no address")
        if not self.allow_private:
            for address in addresses:
                if not ipaddress.ip_address(address).is_global:
                    raise Denied(403, f"{host} resolves to a non-public address")
        return addresses
