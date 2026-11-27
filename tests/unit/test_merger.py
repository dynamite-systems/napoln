"""Tests for napoln.core.merger — three-way merge."""

import pytest

from napoln.core.merger import has_conflict_markers, merge_file, merge_skill


class TestMergeFile:
    """Three-way file merge."""

    @pytest.mark.parametrize(
        "ours_text, base_text, theirs_text, expect_conflicts, expect_contains",
        [
            # No changes anywhere
            ("Same content", "Same content", "Same content", False, "Same content"),
            # Only upstream changed → fast-forward
            ("original", "original", "new from upstream", False, "new from upstream"),
            # Only local changed → keep ours
            ("locally modified", "original", "original", False, "locally modified"),
        ],
        ids=["no-changes", "only-upstream", "only-local"],
    )
    def test_one_side_or_no_changes(
        self,
        tmp_path,
        ours_text,
        base_text,
        theirs_text,
        expect_conflicts,
        expect_contains,
    ):
        (tmp_path / "ours").write_text(ours_text)
        (tmp_path / "base").write_text(base_text)
        (tmp_path / "theirs").write_text(theirs_text)

        merged, has_conflicts = merge_file(
            tmp_path / "ours", tmp_path / "base", tmp_path / "theirs"
        )
        assert has_conflicts is expect_conflicts
        assert expect_contains in merged

    def test_both_changed_different_lines(self, tmp_path):
        """Clean merge when changes don't overlap."""
        base_content = "line 1\nline 2\nline 3\nline 4\nline 5\n"
        ours_content = "line 1 local\nline 2\nline 3\nline 4\nline 5\n"
        theirs_content = "line 1\nline 2\nline 3\nline 4\nline 5 upstream\n"

        (tmp_path / "ours").write_text(ours_content)
        (tmp_path / "base").write_text(base_content)
        (tmp_path / "theirs").write_text(theirs_content)

        merged, has_conflicts = merge_file(
            tmp_path / "ours", tmp_path / "base", tmp_path / "theirs"
        )
        assert merged  # Non-empty result

    def test_both_changed_same_line_conflicts(self, tmp_path):
        """Conflict when both change the same line."""
        (tmp_path / "base").write_text("original line\n")
        (tmp_path / "ours").write_text("local change\n")
        (tmp_path / "theirs").write_text("upstream change\n")

        merged, has_conflicts = merge_file(
            tmp_path / "ours", tmp_path / "base", tmp_path / "theirs"
        )
        assert has_conflicts
        assert "<<<<<<<" in merged


@pytest.fixture
def merge_dirs(tmp_path):
    """Create working/base/new directories for merge_skill tests."""
    dirs = {}
    for name in ("working", "base", "new"):
        d = tmp_path / name
        d.mkdir()
        dirs[name] = d
    return dirs


class TestMergeSkill:
    """Full skill directory merge."""

    def test_fast_forward_unmodified(self, merge_dirs):
        """Unmodified files are fast-forwarded to new upstream."""
        merge_dirs["base"] / "SKILL.md" and (merge_dirs["base"] / "SKILL.md").write_text(
            "V1 content"
        )
        (merge_dirs["working"] / "SKILL.md").write_text("V1 content")
        (merge_dirs["new"] / "SKILL.md").write_text("V2 content")

        updated, conflicted = merge_skill(
            merge_dirs["working"], merge_dirs["base"], merge_dirs["new"]
        )

        assert "SKILL.md" in updated
        assert not conflicted
        assert (merge_dirs["working"] / "SKILL.md").read_text() == "V2 content"

    def test_keeps_local_changes_when_upstream_unchanged(self, merge_dirs):
        """Local changes preserved when upstream didn't change the file."""
        (merge_dirs["base"] / "SKILL.md").write_text("V1 content")
        (merge_dirs["working"] / "SKILL.md").write_text("V1 locally modified")
        (merge_dirs["new"] / "SKILL.md").write_text("V1 content")

        updated, conflicted = merge_skill(
            merge_dirs["working"], merge_dirs["base"], merge_dirs["new"]
        )

        assert not updated
        assert not conflicted
        assert (merge_dirs["working"] / "SKILL.md").read_text() == "V1 locally modified"

    def test_new_file_from_upstream(self, merge_dirs):
        """New files from upstream are added."""
        for d in merge_dirs.values():
            (d / "SKILL.md").write_text("V1")
        (merge_dirs["new"] / "NEW.md").write_text("New file from upstream")

        updated, conflicted = merge_skill(
            merge_dirs["working"], merge_dirs["base"], merge_dirs["new"]
        )

        assert "NEW.md" in updated
        assert (merge_dirs["working"] / "NEW.md").read_text() == "New file from upstream"

    def test_deleted_upstream_unmodified_locally(self, merge_dirs):
        """Files deleted in upstream are removed if unmodified locally."""
        (merge_dirs["base"] / "SKILL.md").write_text("V1")
        (merge_dirs["base"] / "old.md").write_text("to be removed")
        (merge_dirs["working"] / "SKILL.md").write_text("V1")
        (merge_dirs["working"] / "old.md").write_text("to be removed")
        (merge_dirs["new"] / "SKILL.md").write_text("V1")

        updated, conflicted = merge_skill(
            merge_dirs["working"], merge_dirs["base"], merge_dirs["new"]
        )

        assert "old.md" in updated
        assert not (merge_dirs["working"] / "old.md").exists()

    def test_repeated_merge_of_matching_script_is_not_a_conflict(self, tmp_path):
        """A script that already matches upstream is not reported as a conflict.

        The first merge fast-forwards the working copy. A second merge of that
        same directory, which shared agent placements do, must not treat the
        script as a conflict just because it differs from the old base.
        """
        base = tmp_path / "base"
        new = tmp_path / "new"
        work = tmp_path / "work"
        for name, script in (
            ("base", "echo v1\n"),
            ("new", "echo v2\n"),
            ("work", "echo v1\n"),
        ):
            root = tmp_path / name
            (root / "scripts").mkdir(parents=True)
            skill = "# skill new\n" if name == "new" else "# skill base\n"
            (root / "SKILL.md").write_text(skill)
            (root / "scripts" / "run.sh").write_text(script)

        first_updated, first_conflicted = merge_skill(work, base, new)
        assert "scripts/run.sh" in first_updated
        assert "SKILL.md" in first_updated
        assert first_conflicted == []

        updated, conflicted = merge_skill(work, base, new)

        assert conflicted == []
        assert "scripts/run.sh" not in updated
        assert (work / "scripts" / "run.sh").read_text() == "echo v2\n"
        assert (work / "SKILL.md").read_text() == "# skill new\n"

    def test_script_resolved_to_upstream_bytes_is_not_a_conflict(self, tmp_path):
        """Editing a non-Markdown file until it matches upstream clears the conflict."""
        base = tmp_path / "base"
        new = tmp_path / "new"
        work = tmp_path / "work"
        for name in ("base", "new", "work"):
            root = tmp_path / name
            (root / "scripts").mkdir(parents=True)
            (root / "SKILL.md").write_text("# skill\n")
        (base / "scripts" / "run.sh").write_text("echo v1\n")
        (new / "scripts" / "run.sh").write_text("echo v2\n")
        (work / "scripts" / "run.sh").write_text("echo v2\n")

        updated, conflicted = merge_skill(work, base, new)

        assert conflicted == []
        assert updated == []
        assert (work / "scripts" / "run.sh").read_text() == "echo v2\n"

    def test_divergent_script_is_still_a_conflict(self, tmp_path):
        """A non-Markdown file that differs from both base and upstream stays conflicted."""
        base = tmp_path / "base"
        new = tmp_path / "new"
        work = tmp_path / "work"
        for name in ("base", "new", "work"):
            root = tmp_path / name
            (root / "scripts").mkdir(parents=True)
            (root / "SKILL.md").write_text("# skill\n")
        (base / "scripts" / "run.sh").write_text("echo v1\n")
        (new / "scripts" / "run.sh").write_text("echo v2\n")
        (work / "scripts" / "run.sh").write_text("echo local\n")

        updated, conflicted = merge_skill(work, base, new)

        assert conflicted == ["scripts/run.sh"]
        assert updated == []
        assert (work / "scripts" / "run.sh").read_text() == "echo local\n"


class TestHasConflictMarkers:
    """Conflict marker detection."""

    @pytest.mark.parametrize(
        "content, expected",
        [
            ("<<<<<<< local\nfoo\n=======\nbar\n>>>>>>> upstream\n", True),
            ("# Clean file\nNo conflicts here.\n", False),
        ],
        ids=["with-markers", "clean"],
    )
    def test_detects_markers(self, tmp_path, content, expected):
        f = tmp_path / "test.md"
        f.write_text(content)
        assert has_conflict_markers(f) is expected

    def test_nonexistent_file(self, tmp_path):
        assert has_conflict_markers(tmp_path / "nope.md") is False
