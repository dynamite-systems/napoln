"""Regression tests for skills that move within their upstream repo (#119)."""

from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from napoln.cli import app

SOURCE = "fixture-owner/fixture-repo"


def _git(cwd: Path, *args: str, env: dict[str, str]) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, env=env, capture_output=True)


def _skill(path: Path, body: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {path.name}\ndescription: test {path.name}\n---\n{body}\n"
    )


@pytest.fixture
def moved_repo(tmp_path: Path) -> dict[str, str]:
    """A repo where `skills/beta` moved to `bundle/skills/beta` after tag v1.0.0.

    A local bare repo stands in for GitHub via `url.insteadOf`.
    """
    home = tmp_path / "home"
    (home / ".agents" / "skills").mkdir(parents=True)
    (home / ".pi").mkdir()
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("")
    env = {
        "HOME": str(home),
        "NAPOLN_HOME": str(home / ".napoln"),
        "GIT_CONFIG_GLOBAL": str(gitconfig),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "PATH": os.environ["PATH"],
    }
    repo = tmp_path / "work" / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main", env=env)
    _skill(repo / "skills" / "alpha", "v1")
    _skill(repo / "skills" / "beta", "v1")
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-qm", "init", env=env)
    _git(repo, "tag", "v1.0.0", env=env)
    (repo / "bundle" / "skills").mkdir(parents=True)
    _git(repo, "mv", "skills/beta", "bundle/skills/beta", env=env)
    _skill(repo / "bundle" / "skills" / "beta", "v2")
    _git(repo, "commit", "-qam", "move beta", env=env)
    bare = tmp_path / "work" / "repo.git"
    _git(tmp_path, "clone", "-q", "--bare", str(repo), str(bare), env=env)
    gitconfig.write_text(f'[url "file://{bare}"]\n\tinsteadOf = https://github.com/{SOURCE}.git\n')
    return env


def _manifest(env: dict[str, str]) -> dict:
    return tomllib.loads((Path(env["NAPOLN_HOME"]) / "manifest.toml").read_text())


def _add(env: dict[str, str], *extra: str):
    return CliRunner().invoke(app, ["add", SOURCE, "-s", "beta", "--agents", "pi", *extra], env=env)


def test_upgrade_rediscovers_moved_skill(moved_repo):
    env = moved_repo
    result = _add(env)
    assert result.exit_code == 0, result.output
    assert _manifest(env)["skills"]["beta"]["source"] == f"github.com/{SOURCE}/skills/beta"

    result = CliRunner().invoke(app, ["upgrade", "beta", "--version", "main"], env=env)

    assert result.exit_code == 0, result.output
    entry = _manifest(env)["skills"]["beta"]
    assert entry["source"] == f"github.com/{SOURCE}/bundle/skills/beta"
    assert entry["version"] == "main"
    placed = Path(env["HOME"]) / ".agents" / "skills" / "beta" / "SKILL.md"
    assert "v2" in placed.read_text()


def test_upgrade_fails_with_hint_when_moved_skill_is_ambiguous(moved_repo, tmp_path):
    env = moved_repo
    repo = tmp_path / "work" / "repo"
    _skill(repo / "other" / "beta", "dup")
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-qm", "dup beta", env=env)
    _git(repo, "push", "-q", str(tmp_path / "work" / "repo.git"), "main", env=env)
    assert _add(env).exit_code == 0

    result = CliRunner().invoke(app, ["upgrade", "beta", "--version", "main"], env=env)

    assert result.exit_code == 1
    assert "skills/beta" in result.output
    assert "napoln add" in result.output
    assert _manifest(env)["skills"]["beta"]["source"] == f"github.com/{SOURCE}/skills/beta"


def test_readd_moved_skill_repoints_existing_entry(moved_repo):
    env = moved_repo
    assert _add(env).exit_code == 0

    result = _add(env, "--version", "main")

    assert result.exit_code == 0, result.output
    skills = _manifest(env)["skills"]
    assert "fixture-owner.fixture-repo:beta" not in skills
    assert skills["beta"]["source"] == f"github.com/{SOURCE}/bundle/skills/beta"
    assert skills["beta"]["version"] == "main"
    placements = sorted(p.name for p in (Path(env["HOME"]) / ".agents" / "skills").iterdir())
    assert "fixture-owner.fixture-repo:beta" not in placements
