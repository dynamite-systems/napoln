"""Version number for napoln."""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _read_pyproject_version(pyproject: Path | None = None) -> str:
    """Read the package version from pyproject.toml when metadata is unavailable."""
    if pyproject is None:
        parents = Path(__file__).resolve().parents
        if len(parents) <= 3:
            return "0.0.0"
        pyproject = parents[3] / "pyproject.toml"
    if pyproject.is_file():
        with pyproject.open("rb") as f:
            data = tomllib.load(f)
        project = data.get("project")
        if isinstance(project, dict):
            project_version = project.get("version")
            if isinstance(project_version, str):
                return project_version
    return "0.0.0"


def _get_version() -> str:
    """Return the installed napoln package version, falling back to pyproject.toml."""
    try:
        return version("napoln")
    except PackageNotFoundError:
        return _read_pyproject_version()


__version__ = _get_version()
