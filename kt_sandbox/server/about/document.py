"""Render the about document of a sandbox and write it where the agent can read it.

The document is built only from the server's settings and the readers in
:mod:`kt_sandbox.server.about.probe`; it never shows environment variables.
"""

import contextlib
import getpass
import logging
import math
import os
import platform
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from kt_sandbox.server.about import probe
from kt_sandbox.server.settings import ServerSettings

COMMAND = "kt-sandbox-about"
UNKNOWN = "unknown"
LOG = logging.getLogger("kt_sandbox.server.about")


def default_path() -> Path:
    """Where the server writes the document: ``~/.kt-sandbox/about.md``."""
    return Path.home() / ".kt-sandbox" / "about.md"


def size(value: float) -> str:
    """A byte count in binary units: ``256 MiB``, ``41.2 MiB``."""
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024:
            break
        value /= 1024
    else:
        unit = "TiB"
    shown = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{shown} {unit}"


def _network(settings: ServerSettings) -> str:
    match settings.network:
        case "none":
            return "none; the sandbox is offline"
        case "allowlist":
            hosts = ", ".join(settings.allow) or "no hosts"
            return f"only {hosts}, through the proxy set in HTTP_PROXY and HTTPS_PROXY"
        case "open":
            return "open"
    return UNKNOWN


def _sudo(settings: ServerSettings) -> str:
    if settings.sudo is None:
        return UNKNOWN
    return "works without a password" if settings.sudo else "off"


def _user() -> str:
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return UNKNOWN


def _policy(settings: ServerSettings, _: probe.Sources) -> list[str]:
    return [
        f"- Level: {settings.level or UNKNOWN}",
        f"- Network: {_network(settings)}",
        f"- sudo: {_sudo(settings)}",
        f"- User: {_user()}",
        f"- One command: up to {settings.wall_s} s",
        f"- One result: up to {size(settings.output_bytes)} of text",
        f"- Work folder: {settings.workdir}",
    ]


def _of(gauge: probe.Gauge, shown: Callable[[float], str], used: str = "") -> str:
    if gauge.current is None:
        return UNKNOWN
    text = shown(gauge.current) + used
    if gauge.limit == math.inf:
        return f"{text}, no limit"
    if gauge.limit is not None:
        text += f" of {shown(gauge.limit)}"
    return text


def _usage(settings: ServerSettings, sources: probe.Sources) -> list[str]:
    memory_text = _of(probe.memory(sources.cgroup), size, " used")
    cpus = probe.cpus(sources.cgroup)
    cpu_text = (
        UNKNOWN if cpus is None else "no limit" if cpus == math.inf else f"{cpus:g}"
    )
    count = probe.processes(sources.proc)
    tasks = probe.tasks(sources.cgroup)
    process_text = UNKNOWN if count is None else str(count)
    if tasks.current is not None:
        process_text += (
            f" (tasks, counting threads: {_of(tasks, lambda n: str(int(n)))})"
        )
    disk = probe.disk(settings.workdir)
    disk_text = (
        UNKNOWN
        if disk is None
        else f"{size(disk[0])} free in {settings.workdir} (of {size(disk[1])})"
    )
    return [
        f"- Memory: {memory_text}",
        f"- CPUs: {cpu_text}",
        f"- Processes: {process_text}",
        f"- Disk: {disk_text}",
    ]


def _image(_: ServerSettings, sources: probe.Sources) -> list[str]:
    tiers = probe.tiers(sources.image_info)
    found = probe.programs(sources.search_path)
    present = [name for name, ok in found.items() if ok]
    missing = [name for name, ok in found.items() if not ok]
    return [
        f"- Tiers: {', '.join(tiers) if tiers else UNKNOWN}",
        f"- Found: {', '.join(present) or 'none of the listed programs'}",
        f"- Not found: {', '.join(missing) or 'none'}",
    ]


def _python(_: ServerSettings, sources: probe.Sources) -> list[str]:
    found = probe.packages(sources.site_paths, sources.runtime_dir)

    def shown(items: list[tuple[str, str]]) -> str:
        return ", ".join(f"{name} {version}" for name, version in items)

    others = shown(found.others) or "none besides the server's"
    lines = [f"- Python packages: {others}"]
    if found.server:
        lines.append(f"- Used by the server, importable too: {shown(found.server)}")
    return lines


def _section(
    title: str,
    build: Callable[[ServerSettings, probe.Sources], list[str]],
    settings: ServerSettings,
    sources: probe.Sources,
) -> list[str]:
    try:
        body = build(settings, sources)
    except Exception:
        LOG.debug("about: section %s failed", title, exc_info=True)
        body = [f"- {UNKNOWN}"]
    return [f"## {title}", "", *body, ""]


def render(
    settings: ServerSettings,
    sources: probe.Sources = probe.Sources(),
    now: datetime | None = None,
) -> str:
    """Return the about document of the sandbox described by ``settings``."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    title = f"the sandbox {settings.name}" if settings.name else "this sandbox"
    lines = [
        f"# About {title}",
        "",
        f"Written {stamp}. Run `{COMMAND}` for a fresh view.",
        "",
    ]
    lines += _section("Policy", _policy, settings, sources)
    lines += _section("Usage now", _usage, settings, sources)
    lines += _section("Image and programs", _image, settings, sources)
    lines += _section(f"Python {platform.python_version()}", _python, settings, sources)
    try:
        tier_notes = probe.notes(
            sources.image_info, probe.tiers(sources.image_info) or []
        )
    except Exception:
        tier_notes = {}
    for tier, text in tier_notes.items():
        lines += [f"## Notes: {tier}", "", text, ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def write(text: str, path: Path) -> None:
    """Write ``text`` to ``path`` in one step, making its folder if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=".about-", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def publish(
    settings: ServerSettings,
    path: Path | None = None,
    sources: probe.Sources = probe.Sources(),
) -> Path | None:
    """Write the document for a sandbox the manager opened; return where, or None.

    A server without the level's policy (started by hand) writes nothing. A
    failure is logged and returns None.
    """
    if not settings.has_policy:
        return None
    target = path
    try:
        target = target or default_path()
        write(render(settings, sources), target)
    except Exception as exc:
        LOG.warning("could not write %s: %s", target or "the about document", exc)
        return None
    return target
