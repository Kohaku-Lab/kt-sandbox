"""Put the installed kt-sandbox package and its commands into an existing sandbox.

The files travel through Docker's archive API as root, so a stopped sandbox is
upgraded without starting it. The archive opens with an empty file at the
package's path, which makes Docker remove the old package folder before the
new one is unpacked; no stale module survives.
"""

import io
import os
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path

from docker.errors import APIError
from docker.models.containers import Container

from kt_sandbox.errors import ManagerError
from kt_sandbox.manager.builder import PACKAGE_DIR
from kt_sandbox.manager.options import LABEL_NAME

INSTALL_DIR = "/opt/kt-sandbox"
PACKAGE_PATH = f"{INSTALL_DIR}/kt_sandbox"
BIN_DIR = "/usr/local/bin"
# Each command in the image and the module it runs, as the Dockerfile writes them.
WRAPPERS = {
    "kt-sandbox-mcp": "kt_sandbox.server",
    "kt-sandbox": "kt_sandbox",
    "kt-sandbox-about": "kt_sandbox.server.about",
    "kt-sandbox-file": "kt_sandbox.server.files",
}
# Modules the server imports that the package does not carry.
DEPENDENCIES = ("kohakuterrarium", "mcp", "starlette", "uvicorn")
FIND_MISSING = (
    "import importlib.util, sys; "
    "missing = [m for m in sys.argv[1:] if importlib.util.find_spec(m) is None]; "
    "print(' '.join(missing)); sys.exit(1 if missing else 0)"
)
SKIPPED_DIRS = {"__pycache__"}
SKIPPED_SUFFIXES = (".pyc",)


@dataclass(frozen=True)
class Upgraded:
    """What ``upgrade`` put into one sandbox."""

    name: str
    container: str
    files: int
    wrappers: dict[str, str]
    compiled: bool
    checked: bool


def wrapper_script(module: str) -> bytes:
    """The Python script that runs ``module`` from :data:`INSTALL_DIR` as ``__main__``."""
    return (
        f'#!/usr/bin/env python\nimport runpy, sys\nsys.path.insert(0, "{INSTALL_DIR}")\n'
        f'runpy.run_module("{module}", run_name="__main__", alter_sys=True)\n'
    ).encode()


def _info(name: str, kind: bytes, mode: int, size: int = 0) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.mode = mode
    info.size = size
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    info.mtime = int(time.time())
    return info


def _package_files(root: Path) -> list[Path]:
    found = []
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIPPED_DIRS)
        for name in sorted(names):
            path = Path(folder) / name
            if not name.endswith(SKIPPED_SUFFIXES) and path.is_file():
                found.append(path)
    return found


def archive(package_dir: Path = PACKAGE_DIR) -> bytes:
    """Return the tar, rooted at ``/``, of the package at ``package_dir`` and the wrappers."""
    buffer = io.BytesIO()
    package = PACKAGE_PATH.lstrip("/")
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        tar.addfile(_info(package, tarfile.REGTYPE, 0o644), io.BytesIO(b""))
        tar.addfile(_info(package, tarfile.DIRTYPE, 0o755))
        made: set[str] = {package}
        for path in _package_files(package_dir):
            relative = path.relative_to(package_dir)
            for parent in reversed(relative.parents[:-1]):
                folder = f"{package}/{parent.as_posix()}"
                if folder not in made:
                    tar.addfile(_info(folder, tarfile.DIRTYPE, 0o755))
                    made.add(folder)
            data = path.read_bytes()
            tar.addfile(
                _info(
                    f"{package}/{relative.as_posix()}",
                    tarfile.REGTYPE,
                    0o644,
                    len(data),
                ),
                io.BytesIO(data),
            )
        for command, module in WRAPPERS.items():
            script = wrapper_script(module)
            tar.addfile(
                _info(
                    f"{BIN_DIR.lstrip('/')}/{command}",
                    tarfile.REGTYPE,
                    0o755,
                    len(script),
                ),
                io.BytesIO(script),
            )
    return buffer.getvalue()


def upgrade_container(
    container: Container, package_dir: Path = PACKAGE_DIR
) -> Upgraded:
    """Replace the kt-sandbox package and commands in ``container``, running or stopped.

    In a running sandbox the server's dependencies are checked first and the
    package is compiled after. Refuses a container kt-sandbox did not make, a
    read-only one and a running one missing a dependency, with a
    :class:`ManagerError`.
    """
    labels = container.labels or {}
    if LABEL_NAME not in labels:
        raise ManagerError(
            f"container {container.name} was not made by kt-sandbox; only "
            "sandboxes can be upgraded"
        )
    name = labels[LABEL_NAME]
    if (container.attrs.get("HostConfig") or {}).get("ReadonlyRootfs"):
        raise ManagerError(
            f"sandbox {name!r} has a read-only file system, so its package cannot "
            "be replaced. Save it and open the image at a writable level, or "
            "open a new sandbox from a fresh image."
        )
    running = container.status == "running"
    if running:
        found = container.exec_run(["python", "-c", FIND_MISSING, *DEPENDENCIES])
        if found.exit_code != 0:
            missing = found.output.decode(errors="replace").strip() or "python"
            raise ManagerError(
                f"sandbox {name!r} lacks what this kt-sandbox's server needs "
                f"({missing}); its image is too old to upgrade in place. Open a new "
                "sandbox from a current image (`kt-sandbox build`, or pull it)."
            )
    data = archive(package_dir)
    try:
        container.put_archive("/", data)
    except APIError as exc:
        raise ManagerError(
            f"Docker refused to write into sandbox {name!r}: {exc.explanation or exc}"
        ) from exc
    compiled = False
    if running:
        done = container.exec_run(
            ["python", "-m", "compileall", "-q", PACKAGE_PATH], user="root"
        )
        compiled = done.exit_code == 0
    files = sum(1 for _ in _package_files(package_dir))
    return Upgraded(name, container.name, files, dict(WRAPPERS), compiled, running)
