"""Project detection and scope resolution."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from napoln.errors import NapolnError

PROJECT_MARKERS = (".git", ".napoln", ".claude", ".agents", ".cursor", ".hermes")

VALID_SCOPES = ("global", "project")


class ScopeError(NapolnError):
    """Raised when the install scope cannot be determined."""


@dataclass(frozen=True)
class ScopeResolution:
    """The effective scope for a command and, for project scope, its root."""

    scope: str
    project_root: Path | None = None


def find_project_root(start: Path | None = None, home: Path | None = None) -> Path | None:
    """Return the nearest directory at or above *start* that contains a project marker.

    Markers are ``.git``, ``.napoln``, and the agent config directories
    (``.claude``, ``.agents``, ``.cursor``, ``.hermes``). The user's home
    directory and its ancestors are never treated as a project root: the
    agent directories there hold global configuration, so without this
    boundary every directory under ``$HOME`` would look like a project.

    Returns ``None`` if no project root is found.
    """
    start = (start if start is not None else Path.cwd()).resolve()
    home = (home if home is not None else Path.home()).resolve()
    boundary = {home, *home.parents}

    for candidate in (start, *start.parents):
        if candidate in boundary:
            return None
        if any((candidate / marker).exists() for marker in PROJECT_MARKERS):
            return candidate
    return None


def load_config_default_scope(napoln_home: Path) -> str | None:
    """Read the user's configured ``default_scope`` from config.toml.

    Returns ``None`` if the config does not exist, cannot be parsed, or has
    no valid ``default_scope`` set.
    """
    config_path = napoln_home / "config.toml"
    if not config_path.exists():
        return None
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    raw = data.get("napoln", {}).get("default_scope")
    if isinstance(raw, str) and raw in VALID_SCOPES:
        return raw
    return None


def resolve_add_scope(
    *,
    global_flag: bool = False,
    project_flag: bool = False,
    config_default: str | None = None,
    cwd: Path | None = None,
    home: Path | None = None,
) -> ScopeResolution:
    """Resolve the effective scope for ``napoln add``.

    Resolution order:

    1. ``--global`` and ``--project`` together are rejected.
    2. ``--global`` installs globally; ``--project`` installs into *cwd*.
    3. A configured ``default_scope = "global"`` installs globally.
    4. Otherwise (``default_scope = "project"`` or unset), *cwd* must be a
       project root as detected by :func:`find_project_root`.

    Project scope always uses *cwd* as the project root, matching how
    ``remove``, ``upgrade``, ``list``, and ``install`` locate the project
    manifest.

    Raises:
        ScopeError: If the flags conflict, *cwd* is below a project root,
            or no project is found.
    """
    cwd = (cwd if cwd is not None else Path.cwd()).resolve()

    if global_flag and project_flag:
        raise ScopeError(
            "--global and --project cannot be used together.",
            fix="Pass one of --global or --project.",
        )
    if global_flag:
        return ScopeResolution("global")
    if project_flag:
        return ScopeResolution("project", cwd)
    if config_default == "global":
        return ScopeResolution("global")

    root = find_project_root(cwd, home)
    if root == cwd:
        return ScopeResolution("project", cwd)
    if root is not None:
        raise ScopeError(
            f"The current directory is inside the project at {root}, not at its root.",
            fix=(
                f"Run from the project root ({root}), or pass --global to install "
                "for every session."
            ),
        )
    raise ScopeError(
        "No project found in the current directory.",
        cause=(
            "napoln add installs into the current project by default. A project "
            f"is a directory containing one of: {', '.join(PROJECT_MARKERS)}."
        ),
        fix="Run inside a project, or pass --global to install for every session.",
    )
