"""Guard the boundary between commands/ and core/: commands use only public core names."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import napoln.commands

COMMANDS_DIR = Path(napoln.commands.__file__).parent
COMMAND_MODULES = sorted(COMMANDS_DIR.glob("*.py"))


def _private_core_imports(path: Path) -> list[str]:
    """Return `module.name` for each underscore-prefixed name imported from napoln.core."""
    tree = ast.parse(path.read_text(), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("napoln.core"):
            for alias in node.names:
                if alias.name.startswith("_"):
                    found.append(f"{node.module}.{alias.name}")
    return found


@pytest.mark.parametrize("path", COMMAND_MODULES, ids=lambda p: p.name)
def test_commands_do_not_use_private_core_names(path: Path) -> None:
    assert _private_core_imports(path) == []
