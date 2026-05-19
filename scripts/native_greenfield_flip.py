#!/usr/bin/env python3
"""Flip store_backend to native when no graph memory data exists (greenfield install)."""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def graph_memory_has_data() -> bool:
    for db in Path.home().glob(".claude/projects/*/graph_memory/ainl_memory.db"):
        if db.stat().st_size < 8192:
            continue
        try:
            conn = sqlite3.connect(str(db))
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM ainl_graph_nodes"
                ).fetchone()
                if row and row[0] > 0:
                    return True
            except sqlite3.Error:
                if db.stat().st_size >= 8192:
                    return True
            finally:
                conn.close()
        except OSError:
            continue
    return False


def main() -> int:
    if graph_memory_has_data():
        print(
            "ERROR: graph memory data exists — use scripts/migrate_python_to_native.sh",
            file=sys.stderr,
        )
        return 1

    try:
        import ainl_native  # noqa: F401
    except ImportError:
        print("ERROR: ainl_native not importable", file=sys.stderr)
        return 1

    logs = PLUGIN_ROOT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at_unix": int(time.time()),
        "greenfield": True,
        "errors": 0,
        "nodes_written": 0,
        "nodes_total": 0,
        "edges_written": 0,
        "edges_total": 0,
        "projects_committed": 0,
        "projects_count": 0,
        "verify_status": "passed",
    }
    (logs / "migration_latest.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    cfg_path = PLUGIN_ROOT / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.setdefault("memory", {})["store_backend"] = "native"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print("  [ok] greenfield flip: memory.store_backend = native")
    return 0


if __name__ == "__main__":
    sys.exit(main())
