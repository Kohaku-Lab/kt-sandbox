"""Helpers shared by the commands: the manager, and plain-text tables."""

from collections.abc import Sequence

from kt_sandbox.errors import ManagerError


def open_manager():
    """Return a :class:`~kt_sandbox.manager.sandboxes.Manager` on the local Docker engine.

    The manager imports the ``docker`` package, an optional extra, so this
    import waits until a command needs Docker.
    """
    try:
        from kt_sandbox.manager.docker.engine import connect
        from kt_sandbox.manager.sandboxes import Manager
    except ImportError as exc:
        raise ManagerError(
            'the manager needs the docker package: pip install "kt-sandbox[manager]"'
        ) from exc
    return Manager(connect())


def table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Render rows as aligned columns under ``headers``."""
    columns = list(zip(headers, *rows)) if rows else [(h,) for h in headers]
    widths = [max(len(cell) for cell in column) for column in columns]
    lines = ["  ".join(h.ljust(w) for h, w in zip(headers, widths)).rstrip()]
    for row in rows:
        lines.append("  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip())
    return "\n".join(lines)
