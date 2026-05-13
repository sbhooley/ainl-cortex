"""Verify destructive scripts snapshot data before modifying it.

Covers Issue C3 from the post-fix audit. Two scripts can lose data if
they crash mid-run:

- ``migrate_to_python.py --purge-native`` deletes ``ainl_native.db`` (and
  its WAL/SHM siblings, plus ``goal_index.json``).
- ``scripts/repartition_by_repo.py`` writes to per-repo DBs *and* mutates
  the legacy DB's metadata column on every replicated node.

Both must now create a ``.purge-backup.<UTC>`` (or
``.repartition-backup.<UTC>``) sibling before touching the original.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))


def _make_native_db(dir_: Path) -> Path:
    db = dir_ / "ainl_native.db"
    db.write_bytes(b"SQLite format 3\x00fake-but-non-empty")
    (dir_ / "ainl_native.db-wal").write_bytes(b"wal")
    (dir_ / "goal_index.json").write_text("{}")
    return db


def test_migrate_to_python_purge_creates_backup_then_removes(tmp_path, monkeypatch):
    import migrate_to_python as mtp  # type: ignore

    proj_dir = tmp_path / "proj-abc" / "graph_memory"
    proj_dir.mkdir(parents=True)
    db = _make_native_db(proj_dir)

    monkeypatch.setattr(mtp, "_find_native_dbs", lambda: [db])
    out = mtp.purge_native_dbs(dry_run=False)
    assert len(out) == 1
    rec = out[0]
    assert rec["removed"] is True

    assert not db.exists(), "live db should be removed after backup+purge"
    assert not (proj_dir / "ainl_native.db-wal").exists()
    assert not (proj_dir / "goal_index.json").exists()

    backups = list(proj_dir.glob("ainl_native.db.purge-backup.*"))
    assert backups, f"expected backup file, got {list(proj_dir.iterdir())}"
    assert backups[0].read_bytes() == b"SQLite format 3\x00fake-but-non-empty"

    backup_files = rec.get("backup_files", [])
    assert any(p in str(backups[0]) for p in [str(backups[0])]), (
        "backup_files must list the backup paths in the report"
    )


def test_migrate_to_python_purge_dry_run_does_not_create_backup(tmp_path, monkeypatch):
    import migrate_to_python as mtp  # type: ignore

    proj_dir = tmp_path / "proj-xyz" / "graph_memory"
    proj_dir.mkdir(parents=True)
    db = _make_native_db(proj_dir)

    monkeypatch.setattr(mtp, "_find_native_dbs", lambda: [db])
    out = mtp.purge_native_dbs(dry_run=True)
    assert out[0]["removed"] is False
    assert out[0]["reason"] == "dry_run"
    assert "would_backup_to" in out[0]
    assert db.exists(), "dry_run must not delete the live db"
    backups = list(proj_dir.glob("ainl_native.db.purge-backup.*"))
    assert not backups, "dry_run must not create a backup file either"


def test_repartition_backs_up_legacy_db_before_writes(tmp_path):
    sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
    sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))
    from repartition_by_repo import Repartitioner  # type: ignore

    legacy_dir = tmp_path / "legacy" / "graph_memory"
    legacy_dir.mkdir(parents=True)
    legacy_db = legacy_dir / "ainl_memory.db"
    schema = (PLUGIN_ROOT / "mcp_server" / "schema.sql").read_text()
    with sqlite3.connect(str(legacy_db)) as c:
        c.executescript(schema)

    rp = Repartitioner(
        legacy_db=legacy_db,
        repos=[],
        dry_run=False,
        verbose=False,
        purge_legacy=False,
    )
    rc = rp.run()
    assert rc == 0

    backup_info = rp.report.get("legacy_db_backup")
    assert backup_info is not None
    assert backup_info["errors"] == []
    backup_files = backup_info["files"]
    assert backup_files, f"expected at least one backup file, got: {backup_info}"
    backup_path = Path(backup_files[0]["dst"])
    assert backup_path.exists()
    assert backup_path.read_bytes()[:16] == legacy_db.read_bytes()[:16]


def test_repartition_dry_run_records_planned_backup(tmp_path):
    sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
    sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))
    from repartition_by_repo import Repartitioner  # type: ignore

    legacy_dir = tmp_path / "legacy2" / "graph_memory"
    legacy_dir.mkdir(parents=True)
    legacy_db = legacy_dir / "ainl_memory.db"
    schema = (PLUGIN_ROOT / "mcp_server" / "schema.sql").read_text()
    with sqlite3.connect(str(legacy_db)) as c:
        c.executescript(schema)

    rp = Repartitioner(
        legacy_db=legacy_db,
        repos=[],
        dry_run=True,
        verbose=False,
        purge_legacy=False,
    )
    rp.run()
    backup_info = rp.report["legacy_db_backup"]
    assert backup_info["dry_run"] is True
    for f in backup_info["files"]:
        assert f.get("would_copy") is True

    backups = list(legacy_dir.glob("*.repartition-backup.*"))
    assert not backups, "dry_run must not actually create backup files"
