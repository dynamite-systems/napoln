"""Tests for resolve_and_store and ensure_stored in resolver.py."""

from __future__ import annotations

import pytest


@pytest.fixture
def _stored_skill(skill_builder, napoln_home):
    """Use resolve_and_store to store a local skill and return the result."""
    from napoln.core.resolver import resolve_and_store

    skill_dir = skill_builder(name="my-skill", version="1.0.0")
    return resolve_and_store(
        source=str(skill_dir),
        skill_name="my-skill",
        napoln_home=napoln_home,
    )


def test_resolve_and_store_returns_store_path(_stored_skill, napoln_home):
    store_path, content_hash = _stored_skill
    assert store_path.exists()
    assert store_path.is_dir()
    assert (store_path / "SKILL.md").exists()
    assert napoln_home / "store" in store_path.parents


def test_resolve_and_store_returns_content_hash(_stored_skill):
    _, content_hash = _stored_skill
    assert isinstance(content_hash, str)
    assert len(content_hash) > 0


def test_resolve_and_store_bundled_source(napoln_home):
    from napoln.core.resolver import resolve_and_store

    store_path, content_hash = resolve_and_store(
        source="bundled",
        skill_name="napoln-manage",
        napoln_home=napoln_home,
    )
    assert store_path.exists()
    assert (store_path / "SKILL.md").exists()


def test_resolve_and_store_bad_source(napoln_home):
    from napoln.core.resolver import resolve_and_store

    with pytest.raises(Exception):
        resolve_and_store(
            source="/nonexistent/path/to/nowhere",
            skill_name="ghost",
            napoln_home=napoln_home,
        )


def test_store_does_not_depend_on_resolver():
    """store.py must not import resolver.py — dependency is one-way (#43)."""
    import ast
    import inspect

    from napoln.core import store

    tree = ast.parse(inspect.getsource(store))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert "napoln.core.resolver" not in imported


def test_ensure_stored_returns_existing_store_path(_stored_skill, napoln_home):
    from napoln.core.resolver import ensure_stored

    store_path, content_hash = _stored_skill
    result = ensure_stored("my-skill", "1.0.0", content_hash, "/nonexistent/source", napoln_home)
    assert result == store_path


def test_ensure_stored_refetches_missing_skill(skill_builder, napoln_home):
    from napoln.core.resolver import ensure_stored

    skill_dir = skill_builder(name="my-skill", version="1.0.0")
    result = ensure_stored("my-skill", "1.0.0", "deadbeef", str(skill_dir), napoln_home)
    assert (result / "SKILL.md").exists()
    assert napoln_home / "store" in result.parents
