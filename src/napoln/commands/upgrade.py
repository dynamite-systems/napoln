"""napoln upgrade — Upgrade one or all skills."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from napoln import output
from napoln.core import linker, manifest, merger, store
from napoln.core.home import get_napoln_home
from napoln.core.resolver import (
    ParsedSource,
    ResolvedSource,
    SourceType,
    parse_source,
    resolve_git,
    resolve_local,
)
from napoln.errors import ResolverError, SourcePathNotFoundError


def run_upgrade(
    name: str | None = None,
    version_constraint: str | None = None,
    agent_ids: list[str] | None = None,
    dry_run: bool = False,
    force: bool = False,
    scope: str = "global",
    project_root: Path | None = None,
) -> int:
    """Execute the upgrade command.

    Returns:
        Exit code (0=success, 1=error, 2=conflicts).
    """
    import os

    napoln_home = get_napoln_home()
    home = Path(os.environ.get("HOME", Path.home()))
    manifest_path = manifest.get_manifest_path(napoln_home, scope, project_root)
    mf = manifest.read_manifest(manifest_path)

    if not mf.skills:
        output.info("No skills installed.")
        return 0

    skills_to_upgrade = [name] if name else list(mf.skills.keys())
    exit_code = 0

    if dry_run:
        output.dry_run_header()

    for skill_name in skills_to_upgrade:
        if skill_name not in mf.skills:
            output.error(f"Skill '{skill_name}' is not installed.")
            exit_code = 1
            continue

        entry = mf.skills[skill_name]
        code = _upgrade_skill(
            skill_name,
            entry,
            napoln_home,
            home,
            mf,
            manifest_path,
            version_constraint,
            agent_ids,
            dry_run,
            force,
            scope,
            project_root,
        )
        if code > exit_code:
            exit_code = code

    if dry_run:
        output.dry_run_footer()

    return exit_code


def _upgrade_skill(
    skill_name: str,
    entry: manifest.SkillEntry,
    napoln_home: Path,
    home: Path,
    mf: manifest.Manifest,
    manifest_path: Path,
    version_constraint: str | None,
    agent_ids: list[str] | None,
    dry_run: bool,
    force: bool,
    scope: str,
    project_root: Path | None,
) -> int:
    """Upgrade a single skill. Returns exit code."""
    source = entry.source
    # Resolve new version from source
    try:
        parsed = parse_source(entry.source)
        if version_constraint:
            parsed.version = version_constraint

        resolved: ResolvedSource
        if parsed.source_type == SourceType.LOCAL:
            resolved = resolve_local(parsed)
        elif parsed.source_type == SourceType.GIT:
            cache_dir = napoln_home / "cache"
            try:
                result = resolve_git(parsed, cache_dir)
            except SourcePathNotFoundError:
                # The skill moved within its repo; look it up by name instead.
                result = _rediscover_moved_skill(parsed, cache_dir, entry.name or skill_name)
                source = result.source_id
            # resolve_git can return a list for multi-skill repos;
            # during upgrade the manifest source already has a path,
            # so we always expect a single result.
            if isinstance(result, list):
                result_list = cast(list[ResolvedSource], result)
                match = [r for r in result_list if r.skill_name == skill_name]
                if not match:
                    output.error(f"Skill '{skill_name}' not found in resolved sources.")
                    return 1
                resolved = match[0]
            else:
                resolved = result
        else:
            output.info(f"Cannot upgrade '{skill_name}': unsupported source type.")
            return 0
    except ResolverError as e:
        output.error(f"Failed to resolve update for '{skill_name}': {e}", fix=e.fix)
        return 1

    if source != entry.source:
        output.info(f"'{skill_name}' moved upstream: {entry.source} → {source}")

    # Check if there's actually a new version
    from napoln.core.hasher import hash_skill

    new_hash = hash_skill(resolved.skill_dir)
    if new_hash == entry.store_hash and not force:
        output.info(f"'{skill_name}' is already up to date (v{entry.version}).")
        if source != entry.source and not dry_run:
            entry.source = source
            manifest.write_manifest(mf, manifest_path)
        return 0

    new_version = resolved.version

    if dry_run:
        output.would(f"upgrade '{skill_name}' from v{entry.version} to v{new_version}")

    # Store new version
    if not dry_run:
        new_store_path, new_content_hash = store.store_skill(
            resolved.skill_dir, skill_name, new_version, napoln_home
        )
    else:
        new_content_hash = new_hash
        output.would(f"store '{skill_name}' v{new_version}")

    # Get old store base
    old_store = store.get_stored_skill(skill_name, entry.version, entry.store_hash, napoln_home)

    # Merge/replace placements
    agents_to_upgrade = agent_ids if agent_ids else list(entry.agents.keys())
    has_conflicts = False

    for agent_id in agents_to_upgrade:
        if agent_id not in entry.agents:
            continue

        placement = entry.agents[agent_id]
        placement_path = Path(placement.path).expanduser()
        placement_conflicted = False

        if dry_run:
            if force or not old_store or not placement_path.exists():
                output.would(f"replace placement at {placement_path}")
            else:
                output.would(f"merge changes into {placement_path}")
            continue

        if force or not old_store or not placement_path.exists():
            # Force or no base for merge — full replace
            linker.place_skill(new_store_path, placement_path)
            output.success(f"Replaced '{skill_name}' at {placement_path}")
        else:
            # Three-way merge
            updated, conflicted = merger.merge_skill(placement_path, old_store, new_store_path)
            if conflicted:
                has_conflicts = True
                placement_conflicted = True
                output.warning(
                    f"Conflicts in '{skill_name}' at {placement_path}: " + ", ".join(conflicted)
                )
            elif updated:
                output.success(
                    f"Merged '{skill_name}' at {placement_path} ({len(updated)} files updated)"
                )
            else:
                output.info(f"No changes needed for '{skill_name}' at {placement_path}")

        # Only update provenance for clean placements
        if not placement_conflicted:
            linker.write_provenance(
                placement_path,
                source,
                new_version,
                new_content_hash,
                placement.link_mode,
            )

    if not dry_run:
        if has_conflicts:
            # Keep old version in manifest so re-running upgrade works.
            # The new version is in the store for the next merge attempt.
            output.warning(
                f"'{skill_name}' upgraded with conflicts. "
                f"Resolve them, then run `napoln upgrade {skill_name}` again."
            )
        else:
            entry.source = source
            entry.version = new_version
            entry.store_hash = new_content_hash
            from napoln.core.manifest import _now_iso

            entry.updated = _now_iso()
            manifest.write_manifest(mf, manifest_path)
            output.success(f"Upgraded '{skill_name}' to v{new_version}")

    return 2 if has_conflicts else 0


def _rediscover_moved_skill(
    parsed: ParsedSource, cache_dir: Path, upstream_name: str
) -> ResolvedSource:
    """Find a skill by name anywhere in its repo after its recorded path vanished.

    Raises ResolverError unless exactly one skill directory matches.
    """
    recorded_path = parsed.path
    repo_source = f"{parsed.host}/{parsed.owner}/{parsed.repo}"
    parsed.path = ""
    try:
        result = resolve_git(parsed, cache_dir, skill_filter=upstream_name)
    except ResolverError:
        raise ResolverError(
            f"Path '{recorded_path}' does not exist in the repository "
            f"and no skill named '{upstream_name}' was found elsewhere in it",
            fix=f"Check the repository, then re-add the skill:\n  napoln add {repo_source}/<path>",
        )
    if isinstance(result, list):
        candidates = cast(list[ResolvedSource], result)
        paths = "\n".join(f"  napoln add {r.source_id}" for r in candidates)
        raise ResolverError(
            f"Path '{recorded_path}' does not exist in the repository "
            f"and {len(candidates)} skills named '{upstream_name}' were found elsewhere in it",
            fix=f"Re-add the skill from the intended location:\n{paths}",
        )
    return result
