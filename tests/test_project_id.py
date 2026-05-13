"""
Tests for hooks/shared/project_id.py (issue 1 — per-repo project isolation).

Coverage:
  - per_repo mode hashes git toplevel when cwd is inside a git repo
  - per_repo mode hashes cwd when cwd is NOT inside a git repo
  - global mode returns LEGACY_GLOBAL_PROJECT_ID (back-compat escape hatch)
  - get_project_id_chain returns [per_repo, LEGACY] and dedups when equal
  - env var override (AINL_CORTEX_PROJECT_ISOLATION_MODE) wins over config
  - resolver cache survives multiple calls with same cwd
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))


@pytest.fixture(autouse=True)
def _clean_cache_and_env(monkeypatch):
    """Reset the resolver cache + clear env overrides before each test."""
    from shared import project_id as pid_mod
    pid_mod.reset_cache()
    monkeypatch.delenv("AINL_CORTEX_PROJECT_ISOLATION_MODE", raising=False)
    yield
    pid_mod.reset_cache()


def _make_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    # Configure a deterministic identity so commits don't fail on CI.
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@x"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "test"], check=True)


def _expected_hash(p: Path) -> str:
    return hashlib.sha256(str(p.resolve()).encode()).hexdigest()[:16]


class TestPerRepoMode:
    """per_repo (default) — anchor on git toplevel or cwd."""

    def test_git_repo_anchors_on_toplevel(self, tmp_path, monkeypatch):
        from shared import project_id as pid_mod

        repo = tmp_path / "myrepo"
        repo.mkdir()
        _make_git_repo(repo)
        sub = repo / "src" / "deep"
        sub.mkdir(parents=True)

        # default isolation mode is per_repo
        monkeypatch.setattr(pid_mod, "_isolation_mode", lambda: "per_repo")

        pid_top = pid_mod.get_project_id(repo)
        pid_sub = pid_mod.get_project_id(sub)

        # Both cwds inside the same repo collapse to the same id.
        assert pid_top == pid_sub
        # And the id is the hash of the toplevel.
        assert pid_top == _expected_hash(repo)

    def test_two_repos_get_distinct_ids(self, tmp_path, monkeypatch):
        from shared import project_id as pid_mod
        monkeypatch.setattr(pid_mod, "_isolation_mode", lambda: "per_repo")

        repo_a = tmp_path / "repo_a"
        repo_b = tmp_path / "repo_b"
        repo_a.mkdir()
        repo_b.mkdir()
        _make_git_repo(repo_a)
        _make_git_repo(repo_b)

        pid_a = pid_mod.get_project_id(repo_a)
        pid_b = pid_mod.get_project_id(repo_b)

        assert pid_a != pid_b
        assert pid_a == _expected_hash(repo_a)
        assert pid_b == _expected_hash(repo_b)

    def test_non_git_falls_back_to_cwd(self, tmp_path, monkeypatch):
        from shared import project_id as pid_mod
        monkeypatch.setattr(pid_mod, "_isolation_mode", lambda: "per_repo")

        non_git = tmp_path / "loose_dir"
        non_git.mkdir()

        pid = pid_mod.get_project_id(non_git)
        assert pid == _expected_hash(non_git)


class TestGlobalMode:
    """global — back-compat escape hatch returns LEGACY_GLOBAL_PROJECT_ID."""

    def test_global_mode_returns_legacy_id(self, tmp_path, monkeypatch):
        from shared import project_id as pid_mod
        monkeypatch.setattr(pid_mod, "_isolation_mode", lambda: "global")

        repo = tmp_path / "repo_x"
        repo.mkdir()
        _make_git_repo(repo)

        pid = pid_mod.get_project_id(repo)
        assert pid == pid_mod.LEGACY_GLOBAL_PROJECT_ID

    def test_global_mode_alias_compat(self):
        from shared import project_id as pid_mod
        # Keep the old GLOBAL_PROJECT_ID name working.
        assert pid_mod.GLOBAL_PROJECT_ID == pid_mod.LEGACY_GLOBAL_PROJECT_ID


class TestEnvOverride:
    """AINL_CORTEX_PROJECT_ISOLATION_MODE wins over config.json."""

    def test_env_override_to_global(self, tmp_path, monkeypatch):
        from shared import project_id as pid_mod

        repo = tmp_path / "envtest"
        repo.mkdir()
        _make_git_repo(repo)

        # Force the config-based resolver to return per_repo
        monkeypatch.setattr(pid_mod, "_CONFIG_PATH", tmp_path / "missing.json")
        monkeypatch.setenv("AINL_CORTEX_PROJECT_ISOLATION_MODE", "global")
        pid_mod.reset_cache()

        assert pid_mod.get_project_id(repo) == pid_mod.LEGACY_GLOBAL_PROJECT_ID

    def test_env_override_invalid_value_falls_through_to_config(
        self, tmp_path, monkeypatch
    ):
        from shared import project_id as pid_mod

        repo = tmp_path / "envinvalid"
        repo.mkdir()
        _make_git_repo(repo)

        monkeypatch.setenv("AINL_CORTEX_PROJECT_ISOLATION_MODE", "garbage")
        pid_mod.reset_cache()

        # Garbage value ignored — falls back to config (default per_repo).
        pid = pid_mod.get_project_id(repo)
        assert pid == _expected_hash(repo)


class TestProjectChain:
    """get_project_id_chain returns [active, LEGACY] dedup-ordered."""

    def test_chain_is_two_distinct_ids_for_per_repo(self, tmp_path, monkeypatch):
        from shared import project_id as pid_mod
        monkeypatch.setattr(pid_mod, "_isolation_mode", lambda: "per_repo")

        repo = tmp_path / "chainrepo"
        repo.mkdir()
        _make_git_repo(repo)

        chain = pid_mod.get_project_id_chain(repo)
        assert len(chain) == 2
        assert chain[0] == _expected_hash(repo)
        assert chain[1] == pid_mod.LEGACY_GLOBAL_PROJECT_ID

    def test_chain_dedups_when_per_repo_equals_legacy(self, tmp_path, monkeypatch):
        # Run in global mode so the active id IS the legacy id.
        from shared import project_id as pid_mod
        monkeypatch.setattr(pid_mod, "_isolation_mode", lambda: "global")

        chain = pid_mod.get_project_id_chain(tmp_path)
        assert chain == [pid_mod.LEGACY_GLOBAL_PROJECT_ID]


class TestProjectInfo:
    def test_info_includes_isolation_mode_and_chain(self, tmp_path, monkeypatch):
        from shared import project_id as pid_mod
        monkeypatch.setattr(pid_mod, "_isolation_mode", lambda: "per_repo")

        repo = tmp_path / "inforepo"
        repo.mkdir()
        _make_git_repo(repo)

        info = pid_mod.get_project_info(repo)
        assert info["isolation_mode"] == "per_repo"
        assert info["project_id"] == _expected_hash(repo)
        assert info["project_id_chain"][0] == _expected_hash(repo)
        assert info["legacy_global_project_id"] == pid_mod.LEGACY_GLOBAL_PROJECT_ID
        assert info["git_toplevel"] is not None
        assert info["path"] == str(repo.resolve())

    def test_info_for_non_git_cwd_has_no_toplevel(self, tmp_path, monkeypatch):
        from shared import project_id as pid_mod
        monkeypatch.setattr(pid_mod, "_isolation_mode", lambda: "per_repo")

        loose = tmp_path / "loose"
        loose.mkdir()

        info = pid_mod.get_project_info(loose)
        assert info["git_toplevel"] is None
        assert info["project_id"] == _expected_hash(loose)


class TestCacheBehavior:
    def test_resolver_cache_survives_repeated_calls(self, tmp_path, monkeypatch):
        from shared import project_id as pid_mod
        monkeypatch.setattr(pid_mod, "_isolation_mode", lambda: "per_repo")

        repo = tmp_path / "cacherepo"
        repo.mkdir()
        _make_git_repo(repo)

        first = pid_mod.get_project_id(repo)
        second = pid_mod.get_project_id(repo)
        third = pid_mod.get_project_id(repo)
        assert first == second == third
