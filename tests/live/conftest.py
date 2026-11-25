"""Fixtures for the live tests: a Docker engine, the sandbox image, a manager."""

import os
import uuid

import pytest

from kt_sandbox.manager import builder
from kt_sandbox.manager.docker.engine import connect
from kt_sandbox.manager.sandboxes import Manager

LIVE = bool(os.environ.get("KT_SANDBOX_LIVE"))
IMAGE = os.environ.get("KT_SANDBOX_LIVE_IMAGE", "kt-sandbox:live")


def pytest_collection_modifyitems(config, items):
    skip = pytest.mark.skip(reason="set KT_SANDBOX_LIVE=1 with Docker running")
    for item in items:
        if "tests/live" in str(item.fspath) and not LIVE:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def image():
    """The sandbox image under test, built from the installed package unless one is named."""
    if "KT_SANDBOX_LIVE_IMAGE" not in os.environ:
        assert builder.build(tag=IMAGE) == 0, "building the sandbox image failed"
    return IMAGE


@pytest.fixture
def manager():
    return Manager(connect())


@pytest.fixture
def names(manager):
    """Make unique sandbox names and remove everything they leave behind."""
    made: list[str] = []

    def make(prefix: str) -> str:
        name = f"live-{prefix}-{uuid.uuid4().hex[:6]}"
        made.append(name)
        return name

    yield make
    for name in made:
        try:
            manager.rm(name, force=True)
        except Exception:
            pass
    for reference in [
        i.reference for i in manager.saved_images() if i.reference.startswith("live-")
    ]:
        try:
            manager.remove_image(reference)
        except Exception:
            pass
