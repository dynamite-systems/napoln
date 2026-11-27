"""Canonical skill identity on disk after collision-namespacing (#83).

Rule: the placement directory name (= manifest install id) is the canonical
installed identity. The SKILL.md `name:` field is left untouched and preserves
the upstream identity for traceability. See ARCHITECTURE.md, "Skill Identity".

These tests pin that behavior so it can't be flipped silently (e.g. by
stamping the install id into SKILL.md on placement).
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from napoln.cli import app


def _write_skill(root: Path, name: str) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: A test skill.\n"
        'metadata:\n  version: "1.0.0"\n---\n\n# Body\n'
    )
    return skill_dir


def _frontmatter_name(skill_md: Path) -> str:
    _, fm, _ = skill_md.read_text().split("---", 2)
    return yaml.safe_load(fm)["name"]


@pytest.fixture
def colliding_install(tmp_path, monkeypatch):
    """Install two different skills that share the upstream name `shared-name`."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setattr("napoln.core.agents._check_on_path", lambda cmd: False)
    env = {
        "HOME": str(home),
        "NAPOLN_HOME": str(home / ".napoln"),
        "NAPOLN_TELEMETRY": "off",
    }
    runner = CliRunner()
    for repo in ("repo-a", "repo-b"):
        skill = _write_skill(tmp_path / repo, "shared-name")
        result = runner.invoke(app, ["add", str(skill)], env=env)
        assert result.exit_code == 0, result.output
    return home, env, runner


def test_placement_dir_is_install_id_and_frontmatter_keeps_upstream_name(colliding_install):
    home, _, _ = colliding_install
    skills_root = home / ".claude" / "skills"

    first = skills_root / "shared-name"
    namespaced = skills_root / "repo-b:shared-name"
    assert first.is_dir()
    assert namespaced.is_dir()

    # SKILL.md is not rewritten on placement: both keep the upstream name.
    assert _frontmatter_name(first / "SKILL.md") == "shared-name"
    assert _frontmatter_name(namespaced / "SKILL.md") == "shared-name"

    data = tomllib.loads((home / ".napoln" / "manifest.toml").read_text())
    entry = data["skills"]["repo-b:shared-name"]
    assert entry["name"] == "shared-name"
    assert Path(entry["agents"]["claude-code"]["path"]).expanduser().name == namespaced.name


def test_doctor_does_not_flag_namespaced_name_divergence(colliding_install):
    _, env, runner = colliding_install
    result = runner.invoke(app, ["config", "doctor", "--json"], env=env)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output[result.output.index("{") :])
    assert payload["issues"] == []
