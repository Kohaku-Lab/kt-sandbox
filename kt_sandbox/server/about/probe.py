"""Read what a running sandbox has: resource use and limits, tiers, programs and Python packages.

Every reader returns None (or an empty result) for what it cannot read. None
of them runs a program, and ``PATH`` is the only environment variable read.
"""

import importlib.metadata
import math
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import kt_sandbox

CGROUP_ROOT = Path("/sys/fs/cgroup")
PROC_ROOT = Path("/proc")
IMAGE_INFO_DIR = Path("/usr/local/share/kt-sandbox")
RUNTIME_DIR = Path(kt_sandbox.__file__).resolve().parent / "manager" / "image"
RUNTIME_FILE = "runtime-requirements.txt"
RUNTIME_NO_DEPS_FILE = "runtime-requirements-no-deps.txt"
RUNTIME_FILES = (RUNTIME_FILE, RUNTIME_NO_DEPS_FILE)
BASE_TOOLING = frozenset({"pip", "setuptools", "wheel", "kt-sandbox"})
V1_NO_LIMIT = 2**62
PROGRAMS = (
    "python3",
    "pip",
    "curl",
    "sudo",
    "git",
    "gcc",
    "make",
    "node",
    "npm",
    "jq",
    "rg",
    "sqlite3",
    "ffmpeg",
    "convert",
    "magick",
    "pdftoppm",
    "rsvg-convert",
    "chromium",
    "playwright",
)

_NAME = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]*)\])?")
_MARKER_EXTRA = re.compile(r"extra\s*==\s*[\"']([^\"']+)[\"']")


@dataclass(frozen=True)
class Sources:
    """Where the facts are read from; tests point these at fake trees.

    ``search_path`` None means the process's ``PATH``; ``site_paths`` None
    means ``sys.path``.
    """

    cgroup: Path = CGROUP_ROOT
    proc: Path = PROC_ROOT
    image_info: Path = IMAGE_INFO_DIR
    search_path: str | None = None
    site_paths: tuple[str, ...] | None = None
    runtime_dir: Path = RUNTIME_DIR


@dataclass(frozen=True)
class Gauge:
    """A current value and its ceiling: None is unknown, ``math.inf`` is no ceiling."""

    current: int | None
    limit: float | None


@dataclass(frozen=True)
class Packages:
    """Installed Python distributions as ``(name, version)``, sorted by name.

    ``server`` holds the server's direct requirements; ``others`` everything
    that is neither one of them, nor needed by them, nor base tooling.
    """

    others: list[tuple[str, str]]
    server: list[tuple[str, str]]


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None


def _number(path: Path) -> int | None:
    text = _text(path)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _ceiling(path: Path, v1_no_limit: bool = False) -> float | None:
    text = _text(path)
    if text == "max":
        return math.inf
    value = _number(path)
    if value is not None and v1_no_limit and value >= V1_NO_LIMIT:
        return math.inf
    return value


def memory(cgroup: Path) -> Gauge:
    """Memory in use and the memory limit, in bytes (cgroup v2, else v1)."""
    current = _number(cgroup / "memory.current")
    if current is not None:
        return Gauge(current, _ceiling(cgroup / "memory.max"))
    v1 = cgroup / "memory"
    current = _number(v1 / "memory.usage_in_bytes")
    if current is not None:
        return Gauge(current, _ceiling(v1 / "memory.limit_in_bytes", True))
    return Gauge(None, None)


def tasks(cgroup: Path) -> Gauge:
    """Tasks (processes and threads) and their limit (cgroup v2, else v1)."""
    for folder in (cgroup, cgroup / "pids"):
        current = _number(folder / "pids.current")
        if current is not None:
            return Gauge(current, _ceiling(folder / "pids.max"))
    return Gauge(None, None)


def cpus(cgroup: Path) -> float | None:
    """The CPU limit in CPUs (cgroup v2, else v1)."""
    text = _text(cgroup / "cpu.max")
    if text is not None:
        parts = text.split()
        if len(parts) == 2 and parts[0] == "max":
            return math.inf
        try:
            return int(parts[0]) / int(parts[1])
        except (ValueError, IndexError, ZeroDivisionError):
            return None
    quota = _number(cgroup / "cpu" / "cpu.cfs_quota_us")
    period = _number(cgroup / "cpu" / "cpu.cfs_period_us")
    if quota is None or not period:
        return None
    return math.inf if quota < 0 else quota / period


def processes(proc: Path) -> int | None:
    """The number of processes this sandbox can see."""
    try:
        return sum(1 for e in proc.iterdir() if e.name.isdigit() and e.is_dir())
    except OSError:
        return None


def disk(path: Path) -> tuple[int, int] | None:
    """Free and total bytes of the file system holding ``path``."""
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return usage.free, usage.total


def programs(search_path: str | None = None) -> dict[str, bool]:
    """Whether each program in :data:`PROGRAMS` is on the search path."""
    return {name: shutil.which(name, path=search_path) is not None for name in PROGRAMS}


def tiers(image_info: Path) -> list[str] | None:
    """The tiers the image was built with, in build order."""
    text = _text(image_info / "tiers")
    if text is None:
        return None
    names = (line.strip() for line in text.splitlines())
    return list(dict.fromkeys(name for name in names if name))


def notes(image_info: Path, names: Iterable[str]) -> dict[str, str]:
    """The usage notes of the tiers ``names`` that ship one."""
    found = {}
    for name in names:
        if not re.fullmatch(r"[a-z0-9_-]+", name):
            continue
        text = _text(image_info / "notes" / f"{name}.md")
        if text:
            found[name] = text
    return found


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement(
    line: str, extras: frozenset[str] = frozenset()
) -> tuple[str, frozenset[str]] | None:
    """The name and requested extras of one requirement, or None if it does not apply.

    A requirement under ``extra == "x"`` applies only when ``x`` is in ``extras``.
    """
    requirement, _, marker = line.partition(";")
    wanted = {_normalize(extra) for extra in _MARKER_EXTRA.findall(marker)}
    if "extra" in marker and not wanted & extras:
        return None
    match = _NAME.match(requirement)
    if not match:
        return None
    asked = frozenset(
        _normalize(e.strip()) for e in (match.group(2) or "").split(",") if e.strip()
    )
    return _normalize(match.group(1)), asked


def _requirements(path: Path) -> list[tuple[str, frozenset[str]]]:
    found = []
    for line in (_text(path) or "").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            requirement = _requirement(line)
            if requirement:
                found.append(requirement)
    return found


def packages(
    site_paths: tuple[str, ...] | None = None, runtime_dir: Path = RUNTIME_DIR
) -> Packages:
    """List the installed distributions, setting the server's own apart.

    The server's own are the packages in the runtime requirement files and
    what those in the first file need; the second file's are installed
    without their dependencies, so what they declare is not followed.
    """
    found = (
        importlib.metadata.distributions()
        if site_paths is None
        else importlib.metadata.distributions(path=list(site_paths))
    )
    installed: dict[str, importlib.metadata.Distribution] = {}
    for distribution in found:
        name = distribution.metadata["Name"]
        if name:
            installed.setdefault(_normalize(name), distribution)
    expanded = [
        r for r in _requirements(runtime_dir / RUNTIME_FILE) if r[0] in installed
    ]
    alone = [
        r
        for r in _requirements(runtime_dir / RUNTIME_NO_DEPS_FILE)
        if r[0] in installed
    ]
    roots = [name for name, _ in expanded + alone]
    needed, seen, queue = set(roots), set(), list(expanded)
    while queue:
        name, extras = queue.pop()
        if (name, extras) in seen:
            continue
        seen.add((name, extras))
        for line in installed[name].requires or []:
            requirement = _requirement(line, extras)
            if requirement and requirement[0] in installed:
                needed.add(requirement[0])
                queue.append(requirement)

    def listing(names: Iterable[str]) -> list[tuple[str, str]]:
        return [
            (installed[n].metadata["Name"], installed[n].version) for n in sorted(names)
        ]

    others = set(installed) - needed - BASE_TOOLING
    return Packages(others=listing(others), server=listing(dict.fromkeys(roots)))
