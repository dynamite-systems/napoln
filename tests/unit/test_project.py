"""Tests for napoln.core.project — project detection and scope resolution."""

from __future__ import annotations

import pytest

from napoln.core.project import (
    PROJECT_MARKERS,
    ScopeError,
    ScopeResolution,
    find_project_root,
    load_config_default_scope,
    resolve_add_scope,
)


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    (h / ".claude").mkdir(parents=True)
    (h / ".agents").mkdir()
    return h


class TestFindProjectRoot:
    @pytest.mark.parametrize("marker", PROJECT_MARKERS)
    def test_marker_dir_at_start(self, tmp_path, home, marker):
        project = tmp_path / "repo"
        (project / marker).mkdir(parents=True)
        assert find_project_root(project, home) == project.resolve()

    def test_git_file_for_worktree_or_submodule(self, tmp_path, home):
        project = tmp_path / "repo"
        project.mkdir()
        (project / ".git").write_text("gitdir: ../.git/modules/repo")
        assert find_project_root(project, home) == project.resolve()

    def test_walks_up_to_nearest_root(self, tmp_path, home):
        project = tmp_path / "repo"
        (project / ".git").mkdir(parents=True)
        nested = project / "src" / "pkg"
        nested.mkdir(parents=True)
        assert find_project_root(nested, home) == project.resolve()

    def test_no_markers(self, tmp_path, home):
        outside = tmp_path / "outside"
        outside.mkdir()
        assert find_project_root(outside, home) is None

    def test_home_is_not_a_project(self, home):
        assert find_project_root(home, home) is None

    def test_home_agent_dirs_do_not_make_subdirs_projects(self, home):
        downloads = home / "Downloads"
        downloads.mkdir()
        assert find_project_root(downloads, home) is None

    def test_project_under_home(self, home):
        project = home / "code" / "repo"
        (project / ".git").mkdir(parents=True)
        assert find_project_root(project, home) == project.resolve()


class TestLoadConfigDefaultScope:
    @pytest.mark.parametrize("scope", ["project", "global"])
    def test_reads_valid_scope(self, tmp_path, scope):
        (tmp_path / "config.toml").write_text(f'[napoln]\ndefault_scope = "{scope}"\n')
        assert load_config_default_scope(tmp_path) == scope

    def test_returns_none_when_missing(self, tmp_path):
        assert load_config_default_scope(tmp_path) is None

    def test_returns_none_when_invalid(self, tmp_path):
        (tmp_path / "config.toml").write_text('[napoln]\ndefault_scope = "invalid"\n')
        assert load_config_default_scope(tmp_path) is None

    def test_returns_none_when_unparseable(self, tmp_path):
        (tmp_path / "config.toml").write_text("not = [toml")
        assert load_config_default_scope(tmp_path) is None


class TestResolveAddScope:
    @pytest.fixture
    def repo(self, tmp_path):
        r = tmp_path / "repo"
        (r / ".git").mkdir(parents=True)
        return r.resolve()

    @pytest.fixture
    def outside(self, tmp_path):
        o = tmp_path / "outside"
        o.mkdir()
        return o.resolve()

    def test_defaults_to_project_at_project_root(self, repo, home):
        assert resolve_add_scope(cwd=repo, home=home) == ScopeResolution("project", repo)

    def test_config_project_at_project_root(self, repo, home):
        result = resolve_add_scope(config_default="project", cwd=repo, home=home)
        assert result == ScopeResolution("project", repo)

    def test_errors_outside_project(self, outside, home):
        with pytest.raises(ScopeError, match="No project found"):
            resolve_add_scope(cwd=outside, home=home)

    def test_errors_outside_project_with_config_project(self, outside, home):
        with pytest.raises(ScopeError, match="No project found"):
            resolve_add_scope(config_default="project", cwd=outside, home=home)

    def test_errors_in_home_directory(self, home):
        with pytest.raises(ScopeError, match="No project found"):
            resolve_add_scope(cwd=home, home=home)

    def test_errors_in_project_subdirectory(self, repo, home):
        sub = repo / "src"
        sub.mkdir()
        with pytest.raises(ScopeError, match="not at its root") as exc:
            resolve_add_scope(cwd=sub, home=home)
        assert str(repo) in exc.value.fix

    def test_global_flag(self, repo, home):
        assert resolve_add_scope(global_flag=True, cwd=repo, home=home) == ScopeResolution("global")

    def test_project_flag_uses_cwd_even_outside_project(self, outside, home):
        result = resolve_add_scope(project_flag=True, cwd=outside, home=home)
        assert result == ScopeResolution("project", outside)

    def test_conflicting_flags_rejected(self, repo, home):
        with pytest.raises(ScopeError, match="cannot be used together"):
            resolve_add_scope(global_flag=True, project_flag=True, cwd=repo, home=home)

    @pytest.mark.parametrize("where", ["repo", "outside"])
    def test_config_global_installs_globally_anywhere(self, request, home, where):
        cwd = request.getfixturevalue(where)
        result = resolve_add_scope(config_default="global", cwd=cwd, home=home)
        assert result == ScopeResolution("global")

    def test_project_flag_overrides_config_global(self, repo, home):
        result = resolve_add_scope(project_flag=True, config_default="global", cwd=repo, home=home)
        assert result == ScopeResolution("project", repo)
