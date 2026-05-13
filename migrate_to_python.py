#!/usr/bin/env python3
"""
Rollback: flip back to the Python backend after a failed native migration.

This does NOT migrate Rust → Python row-by-row (the Python sidecar still has
the original ainl_memory.db files; nothing was deleted). It does:

  1. Flip config.json memory.store_backend back to "python".
  2. Optionally remove `ainl_native.db` from each project graph_memory dir
     so a future re-migration starts clean (`--purge-native`).
  3. Write a JSON report to `logs/rollback_<UTC>.json`.

Per the migration design (migrate_to_native.py uses a `.staging` file +
os.replace), the Python sidecar always remains untouched. So rollback is
typically a one-line config flip; the purge step is optional.

Usage:
    .venv/bin/python migrate_to_python.py                # flip config only
    .venv/bin/python migrate_to_python.py --purge-native # also delete .db
    .venv/bin/python migrate_to_python.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

PLUGIN_ROOT = Path(__file__).resolve().parent
LOGS_DIR = PLUGIN_ROOT / "logs"


def _find_native_dbs() -> List[Path]:
    base = Path.home() / ".claude" / "projects"
    if not base.exists():
        return []
    return [
        p / "graph_memory" / "ainl_native.db"
        for p in base.iterdir()
        if (p / "graph_memory" / "ainl_native.db").exists()
    ]


def flip_to_python(dry_run: bool = False) -> Dict[str, Any]:
    cfg_path = PLUGIN_ROOT / "config.json"
    cfg = json.loads(cfg_path.read_text())
    current = cfg.get("memory", {}).get("store_backend", "python")
    if current == "python":
        return {"changed": False, "from": current, "to": "python",
                "reason": "already on python"}
    if dry_run:
        return {"changed": False, "from": current, "to": "python",
                "reason": "dry_run"}
    cfg.setdefault("memory", {})["store_backend"] = "python"
    cfg_path.write_text(json.dumps(cfg, indent=2))
    return {"changed": True, "from": current, "to": "python"}


def _backup_path(original: Path, ts: str) -> Path:
    """Return ``<original>.purge-backup.<UTC>`` for the safety copy."""
    return original.with_suffix(original.suffix + f".purge-backup.{ts}")


def _backup_native_db(path: Path, ts: str) -> Dict[str, Any]:
    """Copy ``ainl_native.db`` (and its -wal/-shm/goal_index.json companions)
    into adjacent ``.purge-backup.<UTC>`` files before purging.

    Returns a structured record describing what was copied, so the caller
    can include it in the rollback report. Best-effort: a copy failure
    aborts the purge for *this* DB but does not raise — the caller will
    log the error and skip removal.
    """
    record: Dict[str, Any] = {"path": str(path), "backups": [], "errors": []}
    targets = [path]
    for sfx in ("-wal", "-shm"):
        side = Path(str(path) + sfx)
        if side.exists():
            targets.append(side)
    gi = path.parent / "goal_index.json"
    if gi.exists():
        targets.append(gi)

    for src in targets:
        dst = _backup_path(src, ts)
        try:
            shutil.copy2(src, dst)
            record["backups"].append({"src": str(src), "dst": str(dst),
                                      "bytes": dst.stat().st_size})
        except OSError as e:
            record["errors"].append({"src": str(src), "error": str(e)})
    return record


def purge_native_dbs(dry_run: bool = False) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    ts = _utc_now_str()
    for path in _find_native_dbs():
        size_kib = path.stat().st_size // 1024
        if dry_run:
            out.append({"path": str(path), "size_kib": size_kib,
                        "removed": False, "reason": "dry_run",
                        "would_backup_to": str(_backup_path(path, ts))})
            continue
        # Safety copy BEFORE any unlink. If the backup itself fails, skip
        # the purge for this DB so the user retains a recovery path.
        backup = _backup_native_db(path, ts)
        if backup["errors"]:
            out.append({"path": str(path), "size_kib": size_kib,
                        "removed": False,
                        "reason": "backup_failed",
                        "backup_errors": backup["errors"]})
            continue
        try:
            path.unlink()
            for sfx in ("-wal", "-shm"):
                side = Path(str(path) + sfx)
                if side.exists():
                    side.unlink()
            gi = path.parent / "goal_index.json"
            if gi.exists():
                gi.unlink()
            out.append({"path": str(path), "size_kib": size_kib,
                        "removed": True,
                        "backup_files": [b["dst"] for b in backup["backups"]]})
        except OSError as e:
            out.append({"path": str(path), "size_kib": size_kib,
                        "removed": False, "error": str(e),
                        "backup_files": [b["dst"] for b in backup["backups"]]})
    return out


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_report(report: Dict[str, Any]) -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    path = LOGS_DIR / f"rollback_{_utc_now_str()}.json"
    path.write_text(json.dumps(report, indent=2))
    latest = LOGS_DIR / "rollback_latest.json"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        try:
            os.symlink(path.name, latest)
        except OSError:
            latest.write_text(json.dumps(report, indent=2))
    except OSError:
        pass
    return path


def main():
    parser = argparse.ArgumentParser(
        description="Roll back the native migration: flip config + optionally purge."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--purge-native", action="store_true",
                        help="Also delete ainl_native.db from every project dir")
    args = parser.parse_args()

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Rolling back to Python backend...")

    flip = flip_to_python(dry_run=args.dry_run)
    if flip["changed"]:
        print(f"  config.json: {flip['from']} -> {flip['to']}")
    else:
        print(f"  config.json: no change ({flip.get('reason', '')})")

    purged: List[Dict[str, Any]] = []
    if args.purge_native:
        purged = purge_native_dbs(dry_run=args.dry_run)
        for p in purged:
            tag = "would remove" if args.dry_run else (
                "removed" if p.get("removed") else "FAILED"
            )
            print(f"  {tag}: {p['path']} ({p['size_kib']} KiB)")
            if "error" in p:
                print(f"    error: {p['error']}")

    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "generated_at_unix": int(time.time()),
        "dry_run": args.dry_run,
        "config_flip": flip,
        "purge_native": args.purge_native,
        "purged_dbs": purged,
    }
    report_path = _write_report(report)
    print(f"\nReport: {report_path}")
    print("Done. Restart Claude Code so the plugin re-reads config.json.")


if __name__ == "__main__":
    main()
