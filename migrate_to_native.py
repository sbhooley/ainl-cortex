#!/usr/bin/env python3
"""
One-shot migration: Python ainl_memory.db schema → Rust ainl_native.db schema.

Reads every row from the Python SQLiteGraphStore (ainl_graph_nodes / ainl_graph_edges)
and writes it into NativeGraphStore (Rust ainl-memory). After migration, flip
config.json memory.store_backend from "python" to "native" and restart.

Usage:
    cd ~/.claude/plugins/ainl-graph-memory
    .venv/bin/python migrate_to_native.py [--project-hash HASH] [--dry-run]
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "mcp_server"))
sys.path.insert(0, str(Path(__file__).parent))

from graph_store import SQLiteGraphStore
from native_graph_store import NativeGraphStore
from node_types import GraphNode, GraphEdge, NodeType, EdgeType


def _find_projects() -> list[Path]:
    """Return all project graph_memory dirs that have an ainl_memory.db."""
    base = Path.home() / ".claude" / "projects"
    if not base.exists():
        return []
    return [p / "graph_memory" for p in base.iterdir() if (p / "graph_memory" / "ainl_memory.db").exists()]


def migrate_project(gm_dir: Path, dry_run: bool = False) -> dict:
    py_db = gm_dir / "ainl_memory.db"
    rust_db = gm_dir / "ainl_native.db"

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Migrating: {gm_dir}")
    print(f"  Source:  {py_db} ({py_db.stat().st_size // 1024} KiB)")

    py_store = SQLiteGraphStore(py_db)

    stats = {"nodes": 0, "edges": 0, "skipped": 0, "errors": 0}

    # ── Nodes ─────────────────────────────────────────────────────────────────
    conn = sqlite3.connect(py_db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, node_type, project_id, agent_id, created_at, updated_at, confidence, data, metadata, embedding_text "
        "FROM ainl_graph_nodes"
    ).fetchall()
    edge_rows = conn.execute(
        "SELECT id, edge_type, from_node, to_node, created_at, confidence, project_id, metadata "
        "FROM ainl_graph_edges"
    ).fetchall()
    conn.close()

    if dry_run:
        print(f"  Would migrate {len(rows)} nodes, {len(edge_rows)} edges")
        return {"nodes": len(rows), "edges": len(edge_rows), "skipped": 0, "errors": 0}

    native = NativeGraphStore(rust_db)

    for row in rows:
        try:
            data = json.loads(row["data"]) if row["data"] else {}
            meta = json.loads(row["metadata"]) if row["metadata"] else None
            node = GraphNode(
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
            native.write_node(node)
            stats["nodes"] += 1
        except Exception as e:
            stats["errors"] += 1
            print(f"  ! Node {row['id']} ({row['node_type']}): {e}")

    for row in edge_rows:
        try:
            meta = json.loads(row["metadata"]) if row["metadata"] else None
            edge = GraphEdge(
                id=row["id"],
                edge_type=EdgeType(row["edge_type"]),
                from_node=row["from_node"],
                to_node=row["to_node"],
                created_at=row["created_at"] or 0,
                confidence=float(row["confidence"] or 1.0),
                project_id=row["project_id"],
                metadata=meta,
            )
            native.write_edge(edge)
            stats["edges"] += 1
        except Exception as e:
            stats["errors"] += 1
            print(f"  ! Edge {row['id']} ({row['edge_type']}): {e}")

    rust_size = rust_db.stat().st_size // 1024 if rust_db.exists() else 0
    print(f"  Migrated: {stats['nodes']} nodes, {stats['edges']} edges, {stats['errors']} errors")
    print(f"  Native DB: {rust_db} ({rust_size} KiB)")
    return stats


def flip_backend_config(dry_run: bool = False) -> None:
    cfg_path = Path(__file__).parent / "config.json"
    cfg = json.loads(cfg_path.read_text())
    current = cfg.get("memory", {}).get("store_backend", "python")
    if current == "native":
        print("\nconfig.json already set to native backend.")
        return
    if dry_run:
        print(f"\n[DRY RUN] Would set config.json memory.store_backend: python → native")
        return
    cfg.setdefault("memory", {})["store_backend"] = "native"
    cfg_path.write_text(json.dumps(cfg, indent=2))
    print(f"\nconfig.json updated: memory.store_backend = native")


def main():
    parser = argparse.ArgumentParser(description="Migrate ainl_memory.db to Rust native store")
    parser.add_argument("--project-hash", help="Migrate only this project hash")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing")
    parser.add_argument("--flip-config", action="store_true", help="Set store_backend=native after migration")
    args = parser.parse_args()

    if args.project_hash:
        dirs = [Path.home() / ".claude" / "projects" / args.project_hash / "graph_memory"]
    else:
        dirs = _find_projects()

    if not dirs:
        print("No projects with ainl_memory.db found.")
        return

    total = {"nodes": 0, "edges": 0, "errors": 0}
    for gm_dir in dirs:
        if not (gm_dir / "ainl_memory.db").exists():
            print(f"Skipping {gm_dir} — no ainl_memory.db")
            continue
        s = migrate_project(gm_dir, dry_run=args.dry_run)
        total["nodes"] += s.get("nodes", 0)
        total["edges"] += s.get("edges", 0)
        total["errors"] += s.get("errors", 0)

    print(f"\nTotal: {total['nodes']} nodes, {total['edges']} edges, {total['errors']} errors")

    if args.flip_config:
        flip_backend_config(dry_run=args.dry_run)
    else:
        print("\nTo activate native backend after validating: python migrate_to_native.py --flip-config")


if __name__ == "__main__":
    main()
