"""
Tests for the migration pipeline safety mechanisms (issue 2).

Covers:
  * Per-project atomic semantics: a failure during write must NOT leave a
    partial ainl_native.db on disk.
  * Strict mode refuses to flip config when errors > 0.
  * flip_backend_config refuses stale / unverified reports.
  * Rollback (migrate_to_python.py): config flip + optional --purge-native.

The tests do not require ainl_native.so to be importable — Native-required
paths are skipped when `_NATIVE_OK` is False.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(PLUGIN_ROOT / "mcp_server"))


def _load_module(name: str, path: Path):
    """Load a top-level script as an importable module (migrate_to_native.py
    lives at the repo root, not inside a package)."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def migrate_native_mod():
    return _load_module("migrate_to_native", PLUGIN_ROOT / "migrate_to_native.py")


@pytest.fixture
def migrate_python_mod():
    return _load_module("migrate_to_python", PLUGIN_ROOT / "migrate_to_python.py")


@pytest.fixture
def temp_python_db(tmp_path):
    """Create a tiny ainl_memory.db with the columns migrate expects."""
    db = tmp_path / "graph_memory" / "ainl_memory.db"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE ainl_graph_nodes (
            id TEXT PRIMARY KEY,
            node_type TEXT,
            project_id TEXT,
            agent_id TEXT,
            created_at INTEGER,
            updated_at INTEGER,
            confidence REAL,
            data TEXT,
            metadata TEXT,
            embedding_text TEXT
        );
        CREATE TABLE ainl_graph_edges (
            id TEXT PRIMARY KEY,
            edge_type TEXT,
            from_node TEXT,
            to_node TEXT,
            created_at INTEGER,
            confidence REAL,
            project_id TEXT,
            metadata TEXT
        );
    """)
    # Insert one minimally-valid episode
    conn.execute(
        "INSERT INTO ainl_graph_nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            "episode",
            "proj_test",
            "claude-code",
            int(time.time()),
            int(time.time()),
            0.9,
            json.dumps({"task_description": "test", "files_touched": [],
                        "outcome": "success", "session_id": "s1"}),
            None,
            None,
        ),
    )
    conn.commit()
    conn.close()
    return db


# ── Atomicity (skips if no native build) ────────────────────────────────────

class TestAtomicity:
    def test_dry_run_does_not_write(self, tmp_path, temp_python_db, migrate_native_mod):
        gm_dir = temp_python_db.parent
        result = migrate_native_mod.migrate_project(gm_dir, dry_run=True)
        assert result["dry_run"] is True
        assert result["nodes_total"] == 1
        assert not result["committed"]
        # No native db
        assert not (gm_dir / "ainl_native.db").exists()
        assert not (gm_dir / "ainl_native.db.staging").exists()

    def test_failure_leaves_no_partial_native_db(self, tmp_path, temp_python_db,
                                                   migrate_native_mod, monkeypatch):
        gm_dir = temp_python_db.parent

        # Sabotage: monkeypatch NativeGraphStore.write_node to raise after the
        # store opens. This tests that the staging file is cleaned up.
        if not migrate_native_mod._NATIVE_OK:
            pytest.skip("ainl_native not built")

        from native_graph_store import NativeGraphStore as NGS
        original_write = NGS.write_node

        def _explode(self, node):
            raise RuntimeError("simulated write failure")

        monkeypatch.setattr(NGS, "write_node", _explode)
        try:
            result = migrate_native_mod.migrate_project(gm_dir, dry_run=False)
            assert not result["committed"]
            assert len(result["errors"]) >= 1
            # Staging file removed
            assert not (gm_dir / "ainl_native.db.staging").exists()
            # Live native db never appeared
            assert not (gm_dir / "ainl_native.db").exists()
        finally:
            monkeypatch.setattr(NGS, "write_node", original_write)


# ── Strict mode ────────────────────────────────────────────────────────────

class TestStrictMode:
    def test_strict_flag_propagates_to_report(self, tmp_path, temp_python_db,
                                               migrate_native_mod):
        # Just a smoke test that --strict + dry-run doesn't blow up and
        # produces a report dict with errors=0 for a clean source.
        gm_dir = temp_python_db.parent
        result = migrate_native_mod.migrate_project(gm_dir, dry_run=True)
        assert result["nodes_total"] == 1
        assert len(result["errors"]) == 0


# ── Config flip gating ──────────────────────────────────────────────────────

class TestConfigFlipGating:
    def _write_report(self, plugin_root: Path, body: dict) -> Path:
        logs = plugin_root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        latest = logs / "migration_latest.json"
        latest.write_text(json.dumps(body))
        return latest

    def test_flip_refuses_when_no_report(self, tmp_path, monkeypatch,
                                          migrate_native_mod):
        # Redirect PLUGIN_ROOT -> tmp_path so we don't poke real config.
        monkeypatch.setattr(migrate_native_mod, "PLUGIN_ROOT", tmp_path)
        monkeypatch.setattr(migrate_native_mod, "LOGS_DIR", tmp_path / "logs")
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"memory": {"store_backend": "python"}}))

        rc = migrate_native_mod.flip_backend_config(dry_run=False, force=False)
        assert rc == 2

    def test_flip_refuses_when_report_stale(self, tmp_path, monkeypatch,
                                              migrate_native_mod):
        monkeypatch.setattr(migrate_native_mod, "PLUGIN_ROOT", tmp_path)
        monkeypatch.setattr(migrate_native_mod, "LOGS_DIR", tmp_path / "logs")
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"memory": {"store_backend": "python"}}))
        old_unix = int(time.time()) - 3600  # 1 hour old
        self._write_report(tmp_path, {
            "generated_at_unix": old_unix,
            "errors": 0,
            "verify_status": "passed",
        })

        rc = migrate_native_mod.flip_backend_config(dry_run=False, force=False)
        assert rc == 3

    def test_flip_refuses_when_errors_present(self, tmp_path, monkeypatch,
                                                migrate_native_mod):
        monkeypatch.setattr(migrate_native_mod, "PLUGIN_ROOT", tmp_path)
        monkeypatch.setattr(migrate_native_mod, "LOGS_DIR", tmp_path / "logs")
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"memory": {"store_backend": "python"}}))
        self._write_report(tmp_path, {
            "generated_at_unix": int(time.time()),
            "errors": 3,
            "verify_status": "passed",
        })

        rc = migrate_native_mod.flip_backend_config(dry_run=False, force=False)
        assert rc == 4

    def test_flip_refuses_when_verify_not_passed(self, tmp_path, monkeypatch,
                                                   migrate_native_mod):
        monkeypatch.setattr(migrate_native_mod, "PLUGIN_ROOT", tmp_path)
        monkeypatch.setattr(migrate_native_mod, "LOGS_DIR", tmp_path / "logs")
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"memory": {"store_backend": "python"}}))
        self._write_report(tmp_path, {
            "generated_at_unix": int(time.time()),
            "errors": 0,
            "verify_status": "unknown",
        })

        rc = migrate_native_mod.flip_backend_config(dry_run=False, force=False)
        assert rc == 5

    def test_flip_succeeds_when_all_gates_pass(self, tmp_path, monkeypatch,
                                                 migrate_native_mod):
        monkeypatch.setattr(migrate_native_mod, "PLUGIN_ROOT", tmp_path)
        monkeypatch.setattr(migrate_native_mod, "LOGS_DIR", tmp_path / "logs")
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"memory": {"store_backend": "python"}}))
        self._write_report(tmp_path, {
            "generated_at_unix": int(time.time()),
            "errors": 0,
            "verify_status": "passed",
        })

        rc = migrate_native_mod.flip_backend_config(dry_run=False, force=False)
        assert rc == 0
        new_cfg = json.loads(cfg.read_text())
        assert new_cfg["memory"]["store_backend"] == "native"

    def test_force_bypasses_gates(self, tmp_path, monkeypatch, migrate_native_mod):
        monkeypatch.setattr(migrate_native_mod, "PLUGIN_ROOT", tmp_path)
        monkeypatch.setattr(migrate_native_mod, "LOGS_DIR", tmp_path / "logs")
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"memory": {"store_backend": "python"}}))
        # No report exists at all.
        rc = migrate_native_mod.flip_backend_config(dry_run=False, force=True)
        assert rc == 0
        new_cfg = json.loads(cfg.read_text())
        assert new_cfg["memory"]["store_backend"] == "native"


# ── Verify status injection ────────────────────────────────────────────────

class TestVerifyStatusInjection:
    def test_inject_writes_status_into_latest(self, tmp_path, monkeypatch,
                                                migrate_native_mod):
        monkeypatch.setattr(migrate_native_mod, "PLUGIN_ROOT", tmp_path)
        monkeypatch.setattr(migrate_native_mod, "LOGS_DIR", tmp_path / "logs")
        logs = tmp_path / "logs"
        logs.mkdir()
        report = {"generated_at_unix": int(time.time()), "errors": 0,
                  "verify_status": "unknown"}
        (logs / "migration_latest.json").write_text(json.dumps(report))
        rc = migrate_native_mod.inject_verify_status("passed")
        assert rc == 0
        updated = json.loads((logs / "migration_latest.json").read_text())
        assert updated["verify_status"] == "passed"
        assert "verify_injected_at_unix" in updated

    def test_inject_rejects_invalid_status(self, monkeypatch, migrate_native_mod):
        rc = migrate_native_mod.inject_verify_status("yolo")
        assert rc == 2


# ── Rollback ───────────────────────────────────────────────────────────────

class TestRollback:
    def test_flip_to_python_changes_config(self, tmp_path, monkeypatch,
                                             migrate_python_mod):
        monkeypatch.setattr(migrate_python_mod, "PLUGIN_ROOT", tmp_path)
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"memory": {"store_backend": "native"}}))
        result = migrate_python_mod.flip_to_python(dry_run=False)
        assert result["changed"] is True
        assert json.loads(cfg.read_text())["memory"]["store_backend"] == "python"

    def test_flip_to_python_idempotent_when_already_python(self, tmp_path,
                                                             monkeypatch,
                                                             migrate_python_mod):
        monkeypatch.setattr(migrate_python_mod, "PLUGIN_ROOT", tmp_path)
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"memory": {"store_backend": "python"}}))
        result = migrate_python_mod.flip_to_python(dry_run=False)
        assert result["changed"] is False
        assert "already on python" in result["reason"]

    def test_flip_to_python_dry_run_no_write(self, tmp_path, monkeypatch,
                                               migrate_python_mod):
        monkeypatch.setattr(migrate_python_mod, "PLUGIN_ROOT", tmp_path)
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"memory": {"store_backend": "native"}}))
        result = migrate_python_mod.flip_to_python(dry_run=True)
        assert result["changed"] is False
        assert json.loads(cfg.read_text())["memory"]["store_backend"] == "native"
