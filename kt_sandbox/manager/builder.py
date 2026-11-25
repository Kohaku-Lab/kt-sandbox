"""Build the sandbox image: assemble a build context from the packaged recipe and this package."""

import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

import kt_sandbox

BUILD_DIR = Path(__file__).resolve().parent / "image"
PACKAGE_DIR = Path(kt_sandbox.__file__).resolve().parent
RUNTIME_REQUIREMENTS = "runtime-requirements.txt"
RUNTIME_NO_DEPS = "runtime-requirements-no-deps.txt"


def prepare_context(destination: Path) -> None:
    """Fill ``destination`` with the Dockerfile, the tier files, the runtime
    requirements and a copy of the installed ``kt_sandbox`` package."""
    shutil.copy(BUILD_DIR / "Dockerfile", destination / "Dockerfile")
    for requirements in (RUNTIME_REQUIREMENTS, RUNTIME_NO_DEPS):
        shutil.copy(BUILD_DIR / requirements, destination / requirements)
    for tiers in ("apt", "pip"):
        shutil.copytree(BUILD_DIR / tiers, destination / tiers)
    shutil.copytree(
        PACKAGE_DIR,
        destination / "kt_sandbox",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def build_command(
    context: Path,
    *,
    tag: str,
    extras: Sequence[str] = (),
    apt: Sequence[str] = (),
    pip: Sequence[str] = (),
    base: str | None = None,
    platform: str | None = None,
    push: bool = False,
) -> list[str]:
    """Return the ``docker build`` (or ``buildx``) command for ``context``."""
    command = (
        ["docker", "buildx", "build"] if (platform or push) else ["docker", "build"]
    )
    command += ["-t", tag]
    for name, values in (("EXTRAS", extras), ("EXTRA_APT", apt), ("EXTRA_PIP", pip)):
        if values:
            command += [
                "--build-arg",
                f"{name}={','.join(values) if name == 'EXTRAS' else ' '.join(values)}",
            ]
    if base:
        command += ["--build-arg", f"BASE={base}"]
    if platform:
        command += ["--platform", platform]
    if push:
        command.append("--push")
    return command + [str(context)]


def build(
    *,
    tag: str,
    extras: Sequence[str] = (),
    apt: Sequence[str] = (),
    pip: Sequence[str] = (),
    base: str | None = None,
    platform: str | None = None,
    push: bool = False,
) -> int:
    """Build image ``tag`` with the installed kt-sandbox in it; return Docker's exit code."""
    with tempfile.TemporaryDirectory(prefix="kt-sandbox-build-") as scratch:
        context = Path(scratch)
        prepare_context(context)
        command = build_command(
            context,
            tag=tag,
            extras=extras,
            apt=apt,
            pip=pip,
            base=base,
            platform=platform,
            push=push,
        )
        return subprocess.run(command, check=False).returncode
