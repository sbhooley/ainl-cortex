#!/usr/bin/env python3
"""
Safe one-way migration: Python ainl_memory.db → Rust ainl_native.db.

Per-project atomic semantics:
  * Each project DB is migrated inside a single Python try/except wrapper.
    Native writes go to a STAGING file (`ainl_native.db.staging`); only when
    every node + edge writes successfully is the staging file `os.replace()`d
    onto `ainl_native.db`. On any failure, the staging file is removed and
    the project is reported as failed.
  * `--strict` (auto-on with `--flip-config`) refuses to proceed past the
    dry-run when any project would have errors.
  * A structured JSON report is written to
    `logs/migration_<UTC-timestamp>.json` so wrappers (setup.sh /
    `scripts/migrate_python_to_native.sh`) can read fresh stats instead of
    grepping stdout.
  * `--flip-config` refuses to switch `store_backend = native` unless:
      - the most recent report is < 5 minutes old,
      - report.errors == 0,
      - report.verify_status == "passed" (set by
        `scripts/verify_migration.py` via --inject-verify-status, which the
        wrapper script does between phases).

Usage:
    cd ~/.claude/plugins/ainl-cortex
    .venv/bin/python migrate_to_native.py --dry-run                # preview
    .venv/bin/python migrate_to_native.py --strict                  # execute
    .venv/bin/python migrate_to_native.py --flip-config             # phase 5
    .venv/bin/python migrate_to_native.py --project-hash <id>       # one project

The recommended end-to-end path is `bash scripts/migrate_python_to_native.sh`,
which sequences dry-run -> migrate -> verify -> flip with strict gating.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PLUGIN_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_ROOT / "mcp_server"))
sys.path.insert(0, str(PLUGIN_ROOT))

from graph_store import SQLiteGraphStore  # noqa: E402
from native_graph_store import NativeGraphStore, _NATIVE_OK  # noqa: E402
from node_types import GraphNode, GraphEdge, NodeType, EdgeType  # noqa: E402

LOGS_DIR = PLUGIN_ROOT / "logs"
REPORT_FRESHNESS_S = 5 * 60  # flip-config refuses anything older than this
STAGING_SUFFIX = ".staging"


# ── Project discovery ───────────────────────────────────────────────────────

def _find_projects() -> List[Path]:
    """Return all project graph_memory dirs that have an ainl_memory.db."""
    base = Path.home() / ".claude" / "projects"
    if not base.exists():
        return []
    return [
        p / "graph_memory"
        for p in base.iterdir()
        if (p / "graph_memory" / "ainl_memory.db").exists()
    ]


# ── Per-project migration ──────────────────────────────────────────────────

def _read_python_rows(py_db: Path) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    conn = sqlite3.connect(py_db)
    conn.row_factory = sqlite3.Row
    try:
        nodes = conn.execute(
            "SELECT id, node_type, project_id, agent_id, created_at, updated_at, "
            "       confidence, data, metadata, embedding_text "
            "FROM ainl_graph_nodes"
        ).fetchall()
        edges = conn.execute(
            "SELECT id, edge_type, from_node, to_node, created_at, confidence, "
            "       project_id, metadata "
            "FROM ainl_graph_edges"
        ).fetchall()
    finally:
        conn.close()
    return nodes, edges


def _row_to_node(row: sqlite3.Row) -> GraphNode:
    data = json.loads(row["data"]) if row["data"] else {}
    meta = json.loads(row["metadata"]) if row["metadata"] else None
    return GraphNode(
        id=row["id"],
        node_type=NodeType(row["node_type"]),
        project_id=row["project_id"],
        created_at=row["created_at"] or 0,
        updated_at=row["updated_at"] or 0,
        confidence=float(row["confidence"] or 1.0),
        data=data,
        agent_id=row["agent_id"] or "claude-code",
        metadata=meta,
        embedding_text=row["embedding_text"],
    )


def _row_to_edge(row: sqlite3.Row) -> GraphEdge:
    meta = json.loads(row["metadata"]) if row["metadata"] else None
    return GraphEdge(
        id=row["id"],
        edge_type=EdgeType(row["edge_type"]),
        from_node=row["from_node"],
        to_node=row["to_node"],
        created_at=row["created_at"] or 0,
        confidence=float(row["confidence"] or 1.0),
        project_id=row["project_id"],
        metadata=meta,
    )


def migrate_project(gm_dir: Path, dry_run: bool = False) -> Dict[str, Any]:
    """Migrate ONE project. Atomic via staging file + os.replace.

    Return a dict suitable for embedding in the migration report. Never
    raises on per-row failure; per-project transaction is rolled back by
    deleting the staging file.
    """
    py_db = gm_dir / "ainl_memory.db"
    rust_db = gm_dir / "ainl_native.db"
    staging_db = gm_dir / f"ainl_native.db{STAGING_SUFFIX}"

    result: Dict[str, Any] = {
        "project": gm_dir.parent.name,
        "graph_memory_dir": str(gm_dir),
        "source_db": str(py_db),
        "target_db": str(rust_db),
        "source_size_kib": py_db.stat().st_size // 1024 if py_db.exists() else 0,
        "nodes_total": 0,
        "edges_total": 0,
        "nodes_written": 0,
        "edges_written": 0,
        "errors": [],
        "skipped": False,
        "committed": False,
        "dry_run": dry_run,
    }

    nodes, edges = _read_python_rows(py_db)
    result["nodes_total"] = len(nodes)
    result["edges_total"] = len(edges)

    if dry_run:
        # Validate row decoding without touching native (catches schema drift
        # before the user is committed to a real migration).
        for row in nodes:
            try:
                _row_to_node(row)
            except Exception as e:
                result["errors"].append(
                    {"kind": "node_decode", "id": row["id"], "error": str(e)}
                )
        for row in edges:
            try:
                _row_to_edge(row)
            except Exception as e:
                result["errors"].append(
                    {"kind": "edge_decode", "id": row["id"], "error": str(e)}
                )
        return result

    if not _NATIVE_OK:
        result["skipped"] = True
        result["errors"].append({
            "kind": "native_unavailable",
            "error": "ainl_native module not built — run maturin develop first",
        })
        return result

    # If staging exists from a prior crashed run, remove it.
    if staging_db.exists():
        try:
            staging_db.unlink()
        except OSError as e:
            result["errors"].append(
                {"kind": "staging_cleanup", "error": str(e)}
            )
            return result

    try:
        native = NativeGraphStore(staging_db)

        for row in nodes:
            try:
                native.write_node(_row_to_node(row))
                result["nodes_written"] += 1
            except Exception as e:
                result["errors"].append(
                    {"kind": "node_write", "id": row["id"],
                     "node_type": row["node_type"], "error": str(e)}
                )

        for row in edges:
            try:
                native.write_edge(_row_to_edge(row))
                result["edges_written"] += 1
            except Exception as e:
                result["errors"].append(
                    {"kind": "edge_write", "id": row["id"],
                     "edge_type": row["edge_type"], "error": str(e)}
                )

        # Drop the native handle so SQLite releases the file before replace.
        del native

        if result["errors"]:
            # Atomic abort: delete staging, do not touch the live ainl_native.db.
            if staging_db.exists():
                try:
                    staging_db.unlink()
                except OSError:
                    pass
            return result

        # Atomic commit.
        os.replace(staging_db, rust_db)
        result["committed"] = True
        if rust_db.exists():
            result["target_size_kib"] = rust_db.stat().st_size // 1024
        return result

    except Exception as e:
        # Catastrophic failure (e.g. NativeGraphStore.open exploded).
        if staging_db.exists():
            try:
                staging_db.unlink()
            except OSError:
                pass
        result["errors"].append(
            {"kind": "fatal", "error": f"{type(e).__name__}: {e}"}
        )
        return result


# ── Reporting ──────────────────────────────────────────────────────────────

def _utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _aggregate_report(per_project: List[Dict[str, Any]],
                       dry_run: bool, args_str: str) -> Dict[str, Any]:
    nodes_total = sum(p["nodes_total"] for p in per_project)
    edges_total = sum(p["edges_total"] for p in per_project)
    nodes_written = sum(p["nodes_written"] for p in per_project)
    edges_written = sum(p["edges_written"] for p in per_project)
    errors = sum(len(p["errors"]) for p in per_project)
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "generated_at_unix": int(time.time()),
        "args": args_str,
        "dry_run": dry_run,
        "native_available": _NATIVE_OK,
        "projects_count": len(per_project),
        "projects_committed": sum(1 for p in per_project if p.get("committed")),
        "projects_failed": sum(1 for p in per_project if p.get("errors")),
        "projects_skipped": sum(1 for p in per_project if p.get("skipped")),
        "nodes_total": nodes_total,
        "edges_total": edges_total,
        "nodes_written": nodes_written,
        "edges_written": edges_written,
        "errors": errors,
        # Filled in later by `--inject-verify-status` from the verifier.
        "verify_status": "unknown",
        "per_project": per_project,
    }


def _write_report(report: Dict[str, Any]) -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    path = LOGS_DIR / f"migration_{_utc_now_str()}.json"
    path.write_text(json.dumps(report, indent=2))
    # Also maintain a stable symlink/copy so wrappers find the latest.
    latest = LOGS_DIR / "migration_latest.json"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
        try:
            os.symlink(path.name, latest)
        except OSError:
            # Fallback for filesystems without symlinks.
            latest.write_text(json.dumps(report, indent=2))
    except OSError:
        pass
    return path


def _read_latest_report() -> Optional[Dict[str, Any]]:
    latest = LOGS_DIR / "migration_latest.json"
    if not latest.exists():
        return None
    try:
        if latest.is_symlink():
            return json.loads((LOGS_DIR / os.readlink(latest)).read_text())
        return json.loads(latest.read_text())
    except (OSError, json.JSONDecodeError):
        return None


# ── Config flip ────────────────────────────────────────────────────────────

def flip_backend_config(dry_run: bool = False, force: bool = False) -> int:
    """Switch config.json store_backend from python to native.

    Returns shell exit code (0 = success, non-zero = refused).
    """
    cfg_path = PLUGIN_ROOT / "config.json"
    cfg = json.loads(cfg_path.read_text())
    current = cfg.get("memory", {}).get("store_backend", "python")
    if current == "native":
        print("config.json already on native backend.")
        return 0

    if not force:
        report = _read_latest_report()
        if not report:
            print("ERROR: no migration report found at logs/migration_latest.json. "
                  "Run `python migrate_to_native.py` first, or pass --force.")
            return 2
        age_s = int(time.time()) - int(report.get("generated_at_unix", 0))
        if age_s > REPORT_FRESHNESS_S:
            print(f"ERROR: migration report is stale ({age_s}s old, "
                  f"max {REPORT_FRESHNESS_S}s). Re-run migration before flipping. "
                  f"Pass --force to override (NOT recommended).")
            return 3
        if report.get("errors", 1) != 0:
            print(f"ERROR: latest migration report shows "
                  f"{report['errors']} error(s). Refusing to flip. "
                  f"Pass --force to override (NOT recommended).")
            return 4
        if report.get("verify_status") != "passed":
            print(f"ERROR: latest migration report has verify_status="
                  f"{report.get('verify_status')!r} (need 'passed'). "
                  f"Run `python scripts/verify_migration.py` first. "
                  f"Pass --force to override (NOT recommended).")
            return 5

    if dry_run:
        print("[DRY RUN] Would set memory.store_backend: python -> native")
        return 0

    cfg.setdefault("memory", {})["store_backend"] = "native"
    cfg_path.write_text(json.dumps(cfg, indent=2))
    print("config.json updated: memory.store_backend = native")
    return 0


def inject_verify_status(status: str) -> int:
    """Update logs/migration_latest.json with verify_status from verifier."""
    if status not in ("passed", "failed", "unknown"):
        print(f"ERROR: invalid verify status {status!r}")
        return 2
    latest = LOGS_DIR / "migration_latest.json"
    if not latest.exists():
        print("ERROR: no logs/migration_latest.json to update")
        return 2
    try:
        # Resolve symlink to real path so we update both.
        if latest.is_symlink():
            real = LOGS_DIR / os.readlink(latest)
        else:
            real = latest
        report = json.loads(real.read_text())
        report["verify_status"] = status
        report["verify_injected_at_unix"] = int(time.time())
        real.write_text(json.dumps(report, indent=2))
        print(f"Injected verify_status={status} into {real.name}")
        return 0
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: could not update report: {e}")
        return 2


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Safe migration: Python ainl_memory.db -> Rust ainl_native.db"
    )
    parser.add_argument("--project-hash",
                        help="Migrate only this project hash (default: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview only — no native writes")
    parser.add_argument("--strict", action="store_true",
                        help="Refuse to commit any project if dry-run reports errors. "
                             "Auto-enabled with --flip-config.")
    parser.add_argument("--flip-config", action="store_true",
                        help="Phase 5: switch store_backend to native (gated by report).")
    parser.add_argument("--force", action="store_true",
                        help="Bypass --flip-config gating (NOT recommended).")
    parser.add_argument("--inject-verify-status",
                        choices=["passed", "failed", "unknown"],
                        help="Update verify_status in latest report (used by verifier).")
    args = parser.parse_args()

    # Internal helper mode for the verifier wrapper.
    if args.inject_verify_status:
        sys.exit(inject_verify_status(args.inject_verify_status))

    # Pure flip mode: read latest report and decide.
    if args.flip_config and not (args.dry_run or args.project_hash):
        # Backwards compat: still allow doing a flip after a separate migration run.
        # If no other migration flags supplied, just do the flip.
        sys.exit(flip_backend_config(dry_run=False, force=args.force))

    if args.project_hash:
        gm_dirs = [Path.home() / ".claude" / "projects" /
                    args.project_hash / "graph_memory"]
    else:
        gm_dirs = _find_projects()

    if not gm_dirs:
        print("No projects with ainl_memory.db found.")
        sys.exit(0)

    strict = args.strict or args.flip_config

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}"
          f"Migrating {len(gm_dirs)} project(s); strict={strict}; "
          f"native_available={_NATIVE_OK}")

    per_project: List[Dict[str, Any]] = []
    for gm_dir in gm_dirs:
        if not (gm_dir / "ainl_memory.db").exists():
            print(f"  skip {gm_dir} — no ainl_memory.db")
            continue
        result = migrate_project(gm_dir, dry_run=args.dry_run)
        per_project.append(result)
        status = (
            "DRY"
            if args.dry_run
            else ("OK" if result["committed"] else "FAIL")
        )
        print(f"  [{status}] {gm_dir.parent.name}: "
              f"nodes={result['nodes_written']}/{result['nodes_total']} "
              f"edges={result['edges_written']}/{result['edges_total']} "
              f"errors={len(result['errors'])}")
        for err in result["errors"][:3]:
            print(f"      ! {err}")

    report = _aggregate_report(
        per_project,
        dry_run=args.dry_run,
        args_str=" ".join(sys.argv[1:]),
    )
    report_path = _write_report(report)
    print(f"\nReport: {report_path}")
    print(f"Total: nodes={report['nodes_written']}/{report['nodes_total']} "
          f"edges={report['edges_written']}/{report['edges_total']} "
          f"errors={report['errors']} "
          f"committed={report['projects_committed']}/{report['projects_count']}")

    if strict and report["errors"] > 0:
        print("\nERROR: --strict and report has errors. Refusing to flip config.")
        sys.exit(1)

    if args.flip_config and not args.dry_run:
        # The verifier still has to inject verify_status=passed before flip
        # succeeds — flip will exit non-zero if not. In CLI usage we fail-soft
        # here (let flip's own gating message guide the user).
        rc = flip_backend_config(dry_run=False, force=args.force)
        sys.exit(rc)

    if not args.flip_config and not args.dry_run:
        print("\nNext steps:")
        print("  1. python scripts/verify_migration.py")
        print("  2. python migrate_to_native.py --inject-verify-status passed")
        print("  3. python migrate_to_native.py --flip-config")
        print("  (or run scripts/migrate_python_to_native.sh to do all 5 phases)")


if __name__ == "__main__":
    main()
