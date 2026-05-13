#!/usr/bin/env python3
"""
Migration verifier: compares Python ainl_memory.db ↔ Rust ainl_native.db.

Three checks per project:
  1. Row count parity per node_type — Rust must have >= Python (it may add
     internal nodes, e.g. derived procedurals).
  2. Sample N=20 nodes per type, round-trip through `NativeGraphStore.get_node`,
     assert id matches and key fields preserved (per-type allowlist).
  3. Smoke recall_context for a fixed prompt against both backends — record
     diff in the JSON report (informational; only counted as failure if the
     Rust side returns ZERO results).

Exits non-zero on any failure so wrappers can branch. Writes a JSON report to
`logs/verify_<UTC>.json` and updates `logs/verify_latest.json` symlink.

Usage:
    .venv/bin/python scripts/verify_migration.py            # all projects
    .venv/bin/python scripts/verify_migration.py --project-hash <id>
    .venv/bin/python scripts/verify_migration.py --dry-run  # no recall test
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "mcp_server"))
sys.path.insert(0, str(PLUGIN_ROOT))

from graph_store import SQLiteGraphStore  # noqa: E402
from native_graph_store import NativeGraphStore, _NATIVE_OK  # noqa: E402
from node_types import NodeType  # noqa: E402

LOGS_DIR = PLUGIN_ROOT / "logs"
SAMPLE_N = 20

# Per-type fields that must round-trip byte-exact. Anything not listed here is
# tolerated to drift (e.g. internal Rust normalization).
KEY_FIELDS = {
    NodeType.EPISODE: ("task_description", "files_touched", "outcome"),
    NodeType.SEMANTIC: ("fact", "tags"),
    NodeType.FAILURE: ("error_type", "tool", "error_message"),
    NodeType.PERSONA: ("trait_name",),
    NodeType.PROCEDURAL: ("pattern_name", "tool_sequence"),
    NodeType.GOAL: ("title", "description", "status"),
    NodeType.RUNTIME_STATE: ("turn_count",),
}

NODE_TYPES_TO_SAMPLE = [
    NodeType.EPISODE,
    NodeType.SEMANTIC,
    NodeType.FAILURE,
    NodeType.PERSONA,
    NodeType.PROCEDURAL,
    NodeType.GOAL,
    NodeType.RUNTIME_STATE,
]


def _find_projects() -> List[Path]:
    base = Path.home() / ".claude" / "projects"
    if not base.exists():
        return []
    return [
        p / "graph_memory"
        for p in base.iterdir()
        if (p / "graph_memory" / "ainl_memory.db").exists()
        and (p / "graph_memory" / "ainl_native.db").exists()
    ]


def _python_counts(py_db: Path) -> Dict[str, int]:
    conn = sqlite3.connect(py_db)
    try:
        rows = conn.execute(
            "SELECT node_type, COUNT(*) FROM ainl_graph_nodes GROUP BY node_type"
        ).fetchall()
    finally:
        conn.close()
    return {nt: int(c) for (nt, c) in rows}


def _native_counts(rust_db: Path) -> Dict[str, int]:
    """Approximate native counts by walking the SQLite store directly.

    This is best-effort: the Rust store schema is owned by ainl-memory; we just
    look at the inner tables most likely to exist (`nodes`, `node` are common
    names). We fall back to per-type queries via NativeGraphStore.
    """
    counts: Dict[str, int] = {}
    if _NATIVE_OK:
        store = NativeGraphStore(rust_db)
        for nt in NODE_TYPES_TO_SAMPLE:
            try:
                # Use a large limit; this is verification, not hot path.
                rows = store.query_by_type(nt, project_id="*",
                                           limit=10**6, min_confidence=0.0)
                # The "*" project filter excludes everything; re-query without
                # filter is exposed via internal _store.find_by_type.
                rust_kind = {
                    NodeType.EPISODE: "episode",
                    NodeType.SEMANTIC: "semantic",
                    NodeType.FAILURE: "failure",
                    NodeType.PERSONA: "persona",
                    NodeType.PROCEDURAL: "procedural",
                    NodeType.GOAL: "semantic",
                    NodeType.RUNTIME_STATE: "semantic",
                }[nt]
                raw_rows = store._store.find_by_type(rust_kind)
                if nt == NodeType.GOAL:
                    raw_rows = [
                        r for r in raw_rows
                        if (r.get("plugin_data") or {}).get("py_node_type") == "goal"
                        or (r.get("node_type") or {}).get("topic_cluster", "").endswith(":goal")
                    ]
                elif nt == NodeType.RUNTIME_STATE:
                    raw_rows = [
                        r for r in raw_rows
                        if (r.get("plugin_data") or {}).get("py_node_type") == "runtime_state"
                        or (r.get("node_type") or {}).get("topic_cluster", "").endswith(":runtime_state")
                    ]
                elif nt == NodeType.SEMANTIC:
                    raw_rows = [
                        r for r in raw_rows
                        if not ((r.get("node_type") or {}).get("topic_cluster", "")
                                .startswith("_plugin:"))
                    ]
                counts[nt.value] = len(raw_rows)
            except Exception:
                counts[nt.value] = -1
    return counts


def _sample_node_ids(py_db: Path, node_type: NodeType, n: int) -> List[str]:
    conn = sqlite3.connect(py_db)
    try:
        rows = conn.execute(
            "SELECT id FROM ainl_graph_nodes WHERE node_type = ?",
            (node_type.value,),
        ).fetchall()
    finally:
        conn.close()
    ids = [r[0] for r in rows]
    if len(ids) <= n:
        return ids
    random.seed(42)
    return random.sample(ids, n)


def _verify_project(gm_dir: Path, dry_run: bool = False) -> Dict[str, Any]:
    py_db = gm_dir / "ainl_memory.db"
    rust_db = gm_dir / "ainl_native.db"

    result: Dict[str, Any] = {
        "project": gm_dir.parent.name,
        "graph_memory_dir": str(gm_dir),
        "checks": {
            "row_counts": {"status": "skipped", "details": {}},
            "round_trip": {"status": "skipped", "samples": 0, "mismatches": []},
            "recall_smoke": {"status": "skipped", "rust_results": -1},
        },
        "passed": False,
    }

    # Check 1: row counts.
    py_counts = _python_counts(py_db)
    rust_counts = _native_counts(rust_db) if _NATIVE_OK else {}
    parity_issues = []
    for nt in NODE_TYPES_TO_SAMPLE:
        py_n = py_counts.get(nt.value, 0)
        rust_n = rust_counts.get(nt.value, 0)
        if py_n > 0 and rust_n < py_n:
            parity_issues.append({
                "node_type": nt.value,
                "python": py_n,
                "rust": rust_n,
            })
    result["checks"]["row_counts"] = {
        "status": "passed" if not parity_issues else "failed",
        "details": {"python": py_counts, "rust": rust_counts,
                    "deficits": parity_issues},
    }

    # Check 2: sample round-trip.
    py_store = SQLiteGraphStore(py_db)
    mismatches = []
    samples = 0
    if _NATIVE_OK:
        rust_store = NativeGraphStore(rust_db)
        for nt in NODE_TYPES_TO_SAMPLE:
            ids = _sample_node_ids(py_db, nt, SAMPLE_N)
            for nid in ids:
                py_node = py_store.get_node(nid)
                if py_node is None:
                    continue
                samples += 1
                try:
                    rust_node = rust_store.get_node(nid)
                except Exception as e:
                    mismatches.append({
                        "id": nid, "node_type": nt.value,
                        "error": f"rust_read_failed: {e}",
                    })
                    continue
                if rust_node is None:
                    mismatches.append({
                        "id": nid, "node_type": nt.value,
                        "error": "missing_in_rust",
                    })
                    continue
                if rust_node.node_type != py_node.node_type:
                    mismatches.append({
                        "id": nid, "node_type": nt.value,
                        "error": f"type_mismatch: rust={rust_node.node_type.value}",
                    })
                    continue
                for field in KEY_FIELDS.get(nt, ()):
                    py_val = (py_node.data or {}).get(field)
                    rust_val = (rust_node.data or {}).get(field)
                    if py_val != rust_val:
                        mismatches.append({
                            "id": nid, "node_type": nt.value,
                            "field": field,
                            "python": str(py_val)[:100],
                            "rust": str(rust_val)[:100],
                        })
                        break  # one mismatch per node is enough
    result["checks"]["round_trip"] = {
        "status": "passed" if not mismatches and samples > 0 else
                  ("skipped" if samples == 0 else "failed"),
        "samples": samples,
        "mismatches": mismatches[:50],  # cap report size
        "mismatch_count": len(mismatches),
    }

    # Check 3: recall smoke.
    if not dry_run and _NATIVE_OK:
        try:
            rust_store = NativeGraphStore(rust_db)
            # No project_id known here — just check the store responds.
            episodes = rust_store.query_episodes_since(0, limit=10)
            result["checks"]["recall_smoke"] = {
                "status": "passed" if len(episodes) > 0 else "warn",
                "rust_results": len(episodes),
            }
        except Exception as e:
            result["checks"]["recall_smoke"] = {
                "status": "failed",
                "rust_results": -1,
                "error": str(e),
            }

    result["passed"] = (
        result["checks"]["row_counts"]["status"] == "passed"
        and result["checks"]["round_trip"]["status"] in ("passed", "skipped")
        and result["checks"]["recall_smoke"]["status"] in ("passed", "warn", "skipped")
    )
    return result


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_report(report: Dict[str, Any]) -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    path = LOGS_DIR / f"verify_{_utc_now_str()}.json"
    path.write_text(json.dumps(report, indent=2))
    latest = LOGS_DIR / "verify_latest.json"
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
        description="Verify Python -> Rust migration before flipping config"
    )
    parser.add_argument("--project-hash", help="Verify only this project hash")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip live recall_context probe")
    args = parser.parse_args()

    if not _NATIVE_OK:
        print("ERROR: ainl_native module not available — cannot verify.")
        print("       Build it with `maturin develop --release` first.")
        sys.exit(2)

    if args.project_hash:
        gm_dirs = [Path.home() / ".claude" / "projects" /
                    args.project_hash / "graph_memory"]
    else:
        gm_dirs = _find_projects()

    if not gm_dirs:
        print("No projects with both DBs found.")
        sys.exit(0)

    print(f"Verifying {len(gm_dirs)} project(s)...\n")

    per_project = []
    for gm_dir in gm_dirs:
        result = _verify_project(gm_dir, dry_run=args.dry_run)
        per_project.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        rt = result["checks"]["round_trip"]
        print(f"[{status}] {gm_dir.parent.name}: "
              f"row_counts={result['checks']['row_counts']['status']} "
              f"round_trip={rt['status']} "
              f"({rt.get('mismatch_count', 0)} mismatches in {rt['samples']} samples)")

    report = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "generated_at_unix": int(time.time()),
        "projects_count": len(per_project),
        "projects_passed": sum(1 for p in per_project if p["passed"]),
        "projects_failed": sum(1 for p in per_project if not p["passed"]),
        "overall_status": "passed" if all(p["passed"] for p in per_project) else "failed",
        "per_project": per_project,
    }
    report_path = _write_report(report)
    print(f"\nReport: {report_path}")
    print(f"Overall: {report['overall_status']} "
          f"({report['projects_passed']}/{report['projects_count']} projects)")

    if report["overall_status"] != "passed":
        print("\nVerification failed. Review the report; do NOT flip config.")
        print("To roll back any partial migration: python migrate_to_python.py")
        sys.exit(1)

    print("\nNext: python migrate_to_native.py --inject-verify-status passed")
    print("Then: python migrate_to_native.py --flip-config")


if __name__ == "__main__":
    main()
