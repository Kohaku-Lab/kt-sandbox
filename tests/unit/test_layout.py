"""Repository conventions: every module imports, files stay small, no ``__future__`` imports."""

import ast
import importlib
import pkgutil
import re
from pathlib import Path

import pytest

import kt_sandbox

ROOT = Path(kt_sandbox.__file__).resolve().parent
SOFT_CAP_STATEMENTS = 500
HARD_CAP_STATEMENTS = 1000


def _modules() -> list[str]:
    found = pkgutil.walk_packages([str(ROOT)], prefix="kt_sandbox.")
    return sorted(info.name for info in found)


def _statements(path: Path) -> int:
    """Count statements, leaving out imports and docstrings."""
    total = 0
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.stmt) or isinstance(
            node, (ast.Import, ast.ImportFrom)
        ):
            continue
        is_doc = (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
        total += 0 if is_doc else 1
    return total


@pytest.mark.parametrize("name", _modules())
def test_module_imports(name):
    assert importlib.import_module(name) is not None


def test_every_source_folder_is_a_package():
    folders = {path.parent for path in ROOT.rglob("*.py")}
    missing = [
        str(folder.relative_to(ROOT))
        for folder in folders
        if not (folder / "__init__.py").exists()
    ]
    assert missing == []


def test_every_module_starts_with_a_docstring():
    bare = [
        str(path.relative_to(ROOT))
        for path in ROOT.rglob("*.py")
        if ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) is None
    ]
    assert bare == []


@pytest.mark.parametrize(
    "path", sorted(ROOT.rglob("*.py")), ids=lambda p: str(p.relative_to(ROOT))
)
def test_file_size_and_future_imports(path):
    count = _statements(path)
    assert count <= HARD_CAP_STATEMENTS, f"{path.name} has {count} statements"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    futures = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
    ]
    assert (
        futures == []
    ), f"{path.name} imports __future__; quote the annotation instead"


def test_every_console_script_points_at_a_function():
    text = (ROOT.parent / "pyproject.toml").read_text(encoding="utf-8")
    section = text.split("[project.scripts]", 1)[1].split("\n[", 1)[0]
    scripts = dict(re.findall(r'^([\w-]+) = "([^"]+)"$', section, re.M))
    assert set(scripts) == {"kt-sandbox", "kt-sandbox-mcp", "kt-sandbox-about"}
    for target in scripts.values():
        module, _, function = target.partition(":")
        assert callable(getattr(importlib.import_module(module), function)), target
