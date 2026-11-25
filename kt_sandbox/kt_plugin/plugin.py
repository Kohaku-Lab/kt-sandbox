"""``sandbox.files``: give any tool's file argument a file inside a sandbox, as ``sandbox:<server>/<path>``."""

from pathlib import Path
from typing import Any

from kohakuterrarium.modules.plugin.base import (
    BasePlugin,
    PluginBlockError,
    PluginContext,
)
from kohakuterrarium.modules.plugin.option_validation import validate_plugin_options
from kohakuterrarium.utils.logging import get_logger

from kt_sandbox.kt_plugin.errors import SandboxFileError
from kt_sandbox.kt_plugin.fetch import fetch
from kt_sandbox.kt_plugin.handle import Handle, is_handle, parse_handle
from kt_sandbox.kt_plugin.registry import find_source

logger = get_logger(__name__)

COPY_FOLDER = ".kt-sandbox"
DEFAULT_MAX_BYTES = 20 * 1024 * 1024


class SandboxFilesPlugin(BasePlugin):
    """Replace ``sandbox:<server>/<path>`` in a tool's read-file arguments with a local copy.

    Before each tool call, every argument the tool declares as a ``read`` path
    (``path_arguments``) that holds a handle, alone or in a list, is fetched
    from the sandbox into ``<working dir>/.kt-sandbox/<server>/`` and replaced
    by the copy's absolute path. Priority 0 puts this before the built-in
    ``sandbox`` plugin (priority 1), so its path check sees the local copy.
    """

    name = "sandbox.files"
    priority = 0
    description = (
        "Let any tool argument that takes a file name a file inside a "
        "kt-sandbox: sandbox:<server>/<path>."
    )

    @classmethod
    def option_schema(cls) -> dict[str, dict[str, Any]]:
        return {
            "servers": {
                "type": "list",
                "item_type": "string",
                "default": [],
                "doc": "Names of kt-sandbox servers in the MCP settings.",
            },
            "max_bytes": {
                "type": "int",
                "default": DEFAULT_MAX_BYTES,
                "min": 1,
                "doc": "Largest file fetched from a sandbox, in bytes.",
            },
        }

    def __init__(
        self,
        servers: list[str] | None = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
        **_extra: Any,
    ):
        super().__init__()
        self.options = validate_plugin_options(
            self.name,
            {"servers": servers or [], "max_bytes": max_bytes},
            self.option_schema(),
        )
        self._context: PluginContext | None = None
        self._copies: set[Path] = set()

    @property
    def servers(self) -> list[str]:
        return list(self.options.get("servers") or [])

    def set_options(self, values: dict[str, Any]) -> dict[str, Any]:
        merged = {**self.options, **(values or {})}
        cleaned = validate_plugin_options(self.name, merged, self.option_schema())
        return super().set_options(cleaned)

    async def on_load(self, context: PluginContext) -> None:
        self._context = context

    async def on_unload(self) -> None:
        """Remove the copies this plugin wrote, then the folders they leave empty."""
        for path in sorted(self._copies):
            path.unlink(missing_ok=True)
            folder = path.parent
            while COPY_FOLDER in folder.parts:
                try:
                    folder.rmdir()
                except OSError:
                    break
                if folder.name == COPY_FOLDER:
                    break
                folder = folder.parent
        self._copies.clear()

    def get_prompt_content(self, context: PluginContext) -> str | None:
        if not self.servers:
            return None
        names = ", ".join(f"`{s}`" for s in self.servers)
        return (
            "## Sandbox files\n"
            "A file inside a sandbox can be given to any tool argument that takes "
            "a file, as `sandbox:<server>/<path>` (relative paths are under "
            f"/work); this agent's sandboxes: {names}."
        )

    async def pre_tool_execute(self, args: dict, **kwargs: Any) -> dict | None:
        """Fetch each sandbox file named in a read-path argument and pass its local copy instead."""
        if not self.servers or not isinstance(args, dict):
            return None
        declared = getattr(kwargs.get("tool"), "path_arguments", None) or {}
        names = [a for a, op in declared.items() if op == "read" and a in args]
        if not any(_holds_handle(args[a]) for a in names):
            return None
        root = self._copy_root(kwargs.get("context"))
        new = dict(args)
        try:
            for arg in names:
                new[arg] = await self._replace(args[arg], root)
        except SandboxFileError as exc:
            raise PluginBlockError(str(exc)) from None
        return new

    def _copy_root(self, tool_context: Any) -> Path:
        working = getattr(tool_context, "working_dir", None)
        if working is None and self._context is not None:
            working = self._context.working_dir
        return Path(working or Path.cwd()).resolve() / COPY_FOLDER

    async def _replace(self, value: Any, root: Path) -> Any:
        if isinstance(value, list):
            return [await self._replace(item, root) for item in value]
        if isinstance(value, tuple):
            return tuple([await self._replace(item, root) for item in value])
        if not is_handle(value):
            return value
        handle = parse_handle(value)
        if handle.server not in self.servers:
            known = ", ".join(self.servers)
            raise SandboxFileError(
                f"sandbox:{handle.server}/... names no sandbox server this agent "
                f"knows; known: {known}"
            )
        return str(await self._download(handle, root))

    async def _download(self, handle: Handle, root: Path) -> Path:
        folder = root / handle.server
        target = (folder / Path(*handle.local.parts)).resolve()
        if not target.is_relative_to(folder.resolve()):
            raise SandboxFileError(
                f"sandbox:{handle.server}/{handle.remote} leaves {folder}"
            )
        source = find_source(handle.server)
        data = await fetch(source, handle.remote, int(self.options["max_bytes"]))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self._copies.add(target)
        logger.debug(
            "Fetched sandbox file",
            server=handle.server,
            path=handle.remote,
            size=len(data),
        )
        return target


def _holds_handle(value: Any) -> bool:
    if isinstance(value, (list, tuple)):
        return any(_holds_handle(item) for item in value)
    return is_handle(value)
