"""Images: make sure one is present, save a sandbox as one, list, export and import them."""

from dataclasses import dataclass
from pathlib import Path

import docker
from docker.errors import APIError, ImageLoadError, ImageNotFound
from docker.models.containers import Container

from kt_sandbox.errors import ManagerError
from kt_sandbox.manager import archive
from kt_sandbox.manager.options import LABEL_NAME, LABEL_SAVED


@dataclass(frozen=True)
class SavedImage:
    """A saved sandbox state, as ``images`` shows it."""

    reference: str
    source: str
    size_bytes: int
    created: str


def split_reference(reference: str) -> tuple[str, str]:
    """Split ``repo[:tag]`` into repository and tag (default ``latest``)."""
    head, sep, tail = reference.rpartition(":")
    if sep and "/" not in tail:
        return head, tail
    return reference, "latest"


def ensure(client: docker.DockerClient, reference: str) -> None:
    """Make ``reference`` available locally, pulling it if needed, or raise with a next step."""
    try:
        client.images.get(reference)
        return
    except ImageNotFound:
        pass
    try:
        client.images.pull(reference)
    except APIError as exc:
        raise ManagerError(
            f"image {reference} is not on this machine and could not be pulled "
            f"({exc.explanation or exc}). Build it with `kt-sandbox build -t {reference}`, "
            "or name an image you have."
        ) from exc


def commit(
    client: docker.DockerClient, container: Container, reference: str
) -> SavedImage:
    """Save the sandbox's current state as image ``reference`` and return it."""
    repository, tag = split_reference(reference)
    try:
        container.commit(
            repository=repository, tag=tag, changes=[f"LABEL {LABEL_SAVED}=1"]
        )
    except APIError as exc:
        raise ManagerError(
            f"Docker could not save the sandbox: {exc.explanation or exc}"
        ) from exc
    return describe(client.images.get(f"{repository}:{tag}"))


def describe(image) -> SavedImage:
    """Describe an image for listings."""
    tags = image.tags
    labels = image.labels or {}
    return SavedImage(
        reference=tags[0] if tags else image.short_id,
        source=labels.get(LABEL_NAME, "?"),
        size_bytes=image.attrs.get("Size", 0),
        created=str(image.attrs.get("Created", ""))[:19].replace("T", " "),
    )


def saved(client: docker.DockerClient) -> list[SavedImage]:
    """Return the images saved from sandboxes, newest first."""
    found = client.images.list(filters={"label": f"{LABEL_SAVED}=1"})
    return sorted((describe(i) for i in found), key=lambda i: i.created, reverse=True)


def remove(client: docker.DockerClient, reference: str) -> None:
    """Delete a saved image; refuse an image that was not saved by kt-sandbox."""
    try:
        image = client.images.get(reference)
    except ImageNotFound:
        raise ManagerError(
            f"no image {reference!r}. See `kt-sandbox images`."
        ) from None
    if (image.labels or {}).get(LABEL_SAVED) != "1":
        raise ManagerError(
            f"{reference} was not saved by kt-sandbox; remove it with docker."
        )
    try:
        client.images.remove(reference)
    except APIError as exc:
        raise ManagerError(
            f"Docker could not remove {reference}: {exc.explanation or exc}"
        ) from exc


def tag_to_save(image, reference: str) -> str | bool:
    """Return the ``named`` argument that keeps ``reference`` as the tag in a tarball."""
    canonical = ":".join(split_reference(reference))
    for candidate in (reference, canonical):
        if candidate in image.tags:
            return candidate
    return True


def export(
    client: docker.DockerClient, reference: str, path: Path, *, force: bool = False
) -> int:
    """Stream image ``reference`` into the tarball ``path``; return the file size in bytes."""
    archive.check_destination(path, force=force)
    try:
        image = client.images.get(reference)
    except ImageNotFound:
        raise ManagerError(
            f"no image {reference!r}. See `kt-sandbox images` or `docker images`."
        ) from None
    try:
        return archive.write_chunks(
            image.save(named=tag_to_save(image, reference)), path, force=force
        )
    except APIError as exc:
        raise ManagerError(
            f"Docker could not export {reference}: {exc.explanation or exc}"
        ) from exc


def load(client: docker.DockerClient, path: Path) -> list[archive.LoadedImage]:
    """Load the images in the tarball ``path`` (plain or gzip) and describe them."""
    archive.check_source(path)
    try:
        with open(path, "rb") as stream:
            loaded = client.images.load(stream)
    except (APIError, ImageLoadError) as exc:
        detail = getattr(exc, "explanation", None) or exc
        raise ManagerError(f"Docker could not import {path}: {detail}") from exc
    found = []
    for image in loaded:
        saved = (image.labels or {}).get(LABEL_SAVED) == "1"
        for reference in image.tags or [image.short_id]:
            found.append(archive.LoadedImage(reference=reference, saved=saved))
    return found
