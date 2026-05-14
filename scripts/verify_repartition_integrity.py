#!/usr/bin/env python3
"""
Verify per-repo graph DB integrity after repartition.

Checks that every row in ``ainl_graph_edges`` references node ids that exist in
``ainl_graph_nodes`` in the *same* database file (SQLite FK is only enforced
when PRAGMA foreign_keys=ON; this script catches drift regardless).

Usage:
  python scripts/verify_repartition_integrity.py ~/.claude/projects/<hash>/graph_memory/ainl_memory.db
  python scripts/verify_repartition_integrity.py --all-under ~/.claude/projects
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List


def _check_db(db_path: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {"db": str(db_path), "orphan_edges": [], "ok": True}
    if not db_path.exists():
        out["ok"] = False
        out["error"] = "missing"
        return out
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        node_ids = {r[0] for r in conn.execute("SELECT id FROM ainl_graph_nodes")}
        for edge in conn.execute("SELECT id, from_node, to_node FROM ainl_graph_edges"):
            fn = edge["from_node"]
            tn = edge["to_node"]
            if fn not in node_ids or tn not in node_ids:
                out["orphan_edges"].append(
                    {"edge_id": edge["id"], "from_node": fn, "to_node": tn}
                )
                out["ok"] = False
    finally:
        conn.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db", nargs="?", type=Path, help="Path to ainl_memory.db")
    ap.add_argument(
        "--all-under",
        type=Path,
        help="Walk under this directory for .../graph_memory/ainl_memory.db files",
    )
    ap.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = ap.parse_args()

    targets: List[Path] = []
    if args.db:
        targets.append(args.db)
    if args.all_under:
        root = args.all_under.expanduser()
        targets.extend(sorted(root.glob("**/graph_memory/ainl_memory.db")))

    if not targets:
        ap.print_help()
        return 2

    results = [_check_db(p) for p in targets]
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            status = "OK" if r.get("ok") else "FAIL"
            print(f"[{status}] {r.get('db')}")
            if r.get("error"):
                print(f"  error: {r['error']}")
            for o in r.get("orphan_edges") or []:
                print(f"  orphan edge {o['edge_id']}: {o['from_node']} -> {o['to_node']}")
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
