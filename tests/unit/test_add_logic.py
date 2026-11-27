"""Tests for napoln.commands.add — initialization logic."""

from __future__ import annotations

import tomllib

import pytest

from napoln.commands.add import (
    _ensure_initialized,
    _install_single_skill,
    _pick_from_multi_skill_repo,
)
from napoln.core import manifest
from napoln.core.agents import AGENTS
from napoln.core.hasher import hash_skill
from napoln.core.resolver import ParsedSource, ResolvedSource, SourceType
from napoln.errors import MultipleSkillsError


class TestEnsureInitialized:
    def test_creates_directory_structure(self, tmp_path):
        home = tmp_path / ".napoln"
        _ensure_initialized(home)

        assert home.is_dir()
        assert (home / "store").is_dir()
        assert (home / "cache").is_dir()

    def test_writes_default_config(self, tmp_path):
        home = tmp_path / ".napoln"
        _ensure_initialized(home)

        config_path = home / "config.toml"
        assert config_path.exists()
        data = tomllib.loads(config_path.read_text())
        assert data["napoln"]["default_agents"] == []
        assert data["napoln"]["default_scope"] == "global"
        assert data["telemetry"]["enabled"] is False

    def test_does_not_overwrite_existing_config(self, tmp_path):
        home = tmp_path / ".napoln"
        _ensure_initialized(home)

        config_path = home / "config.toml"
        config_path.write_text('[napoln]\ndefault_scope = "project"\n')

        _ensure_initialized(home)

        data = tomllib.loads(config_path.read_text())
        assert data["napoln"]["default_scope"] == "project"

    def test_creates_nested_parent_dirs(self, tmp_path):
        home = tmp_path / "deep" / "nested" / ".napoln"
        _ensure_initialized(home)

        assert home.is_dir()
        assert (home / "store").is_dir()


class TestInstallSingleSkillFailures:
    """Store and placement failures are reported and abort with exit code 1."""

    @staticmethod
    def _corrupt_store(skill_dir, napoln_home, home):
        entry = napoln_home / "store" / "test-skill" / f"1.0.0-{hash_skill(skill_dir)}"
        entry.mkdir(parents=True)
        (entry / "SKILL.md").write_text("tampered")

    @staticmethod
    def _block_placement(skill_dir, napoln_home, home):
        (home / ".claude").write_text("not a directory")

    @pytest.mark.parametrize(
        "break_install, message",
        [(_corrupt_store, "Failed to store skill"), (_block_placement, "Failed to place")],
        ids=["store-error", "placement-error"],
    )
    def test_failure_is_reported(
        self, skill_builder, tmp_home, napoln_home, capsys, break_install, message
    ):
        skill_dir = skill_builder("test-skill")
        break_install(skill_dir, napoln_home, tmp_home)
        resolved = ResolvedSource(
            source_type=SourceType.LOCAL,
            source_id=str(skill_dir),
            skill_dir=skill_dir,
            version="1.0.0",
        )
        manifest_path = napoln_home / "manifest.toml"

        code = _install_single_skill(
            resolved,
            "test-skill",
            [AGENTS["claude-code"]],
            napoln_home,
            tmp_home,
            "global",
            None,
            manifest.Manifest(),
            manifest_path,
            False,
        )

        assert code == 1
        assert message in capsys.readouterr().err
        assert not manifest_path.exists()


class TestPickFromMultiSkillRepo:
    def test_unreadable_manifest_does_not_block_picker(
        self, tmp_path, napoln_home, skill_builder, monkeypatch
    ):
        """A corrupt manifest only loses the 'installed' markers; the picker still runs."""
        monkeypatch.chdir(tmp_path)
        (napoln_home / "manifest.toml").write_text("[invalid toml")
        skill_dir = skill_builder("alpha")
        offered = []
        monkeypatch.setattr(
            "napoln.commands.add.pick_skills", lambda choices: offered.extend(choices) or []
        )
        parsed = ParsedSource(
            source_type="git",
            host="github.com",
            owner="owner",
            repo="repo",
            path="",
            version="",
            original="owner/repo",
        )

        result = _pick_from_multi_skill_repo(
            MultipleSkillsError(skill_dir.parent, [skill_dir]),
            parsed,
            "owner/repo",
            None,
            napoln_home,
        )

        assert result is None
        assert [(c.name, c.installed) for c in offered] == [("alpha", False)]
