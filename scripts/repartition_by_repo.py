#!/usr/bin/env python3
"""
One-time backfill: re-key the legacy global memory bucket into per-repo buckets.

Background
----------
Before issue 1 was fixed, every Claude Code session on this machine wrote to
the SAME bucket: `~/.claude/projects/<LEGACY>/graph_memory/ainl_memory.db`.
After issue 1, sessions write to `~/.claude/projects/<per_repo>/graph_memory/`.

This script reads the legacy bucket, decides which per-repo bucket each node
belongs to (via files_touched longest-prefix match), and replicates it there.
Edges whose endpoints both land in the same repo are replicated; cross-repo
edges are dropped with a warning.

The legacy bucket is left intact. Pass `--purge-legacy` to drop the original
nodes after a successful run (no automatic purge).

Algorithm
---------
1. Discover candidate repos (from common workspace dirs + config-driven list).
2. For each EPISODE: longest-prefix match `files_touched` against repo paths;
   majority winner gets the episode (ties / no match → keep in legacy).
3. FAILURE: same logic on `data.file`.
4. SEMANTIC: follow DERIVES_FROM edge to source episode, inherit its repo.
5. PROCEDURAL: aggregate over `evidence_ids` episodes.
6. PERSONA: persona is global by design — keep in legacy.
7. GOAL: keep in legacy unless explicitly tagged with a repo path.
8. RUNTIME_STATE: drop (project-scoped state has no meaning after re-key).

Output: `logs/repartition_report.json` summarises decisions per node type.

Usage
-----
  python scripts/repartition_by_repo.py --dry-run        # show plan, no writes
  python scripts/repartition_by_repo.py --report         # verbose decisions
  python scripts/repartition_by_repo.py                  # execute
  python scripts/repartition_by_repo.py --purge-legacy   # drop legacy nodes
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Make the plugin's hooks/shared importable for project_id resolution.
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))
sys.path.insert(0, str(PLUGIN_ROOT / "mcp_server"))

from shared.project_id import (  # noqa: E402
    LEGACY_GLOBAL_PROJECT_ID,
    _hash_anchor,
)


# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_SEARCH_PATHS = [
    Path.home() / ".openclaw" / "workspace",
    Path.home() / "Projects",
    Path.home() / "code",
    Path.home() / "dev",
    Path.home() / "work",
]

PROJECTS_ROOT = Path.home() / ".claude" / "projects"
LEGACY_DB_PATH = PROJECTS_ROOT / LEGACY_GLOBAL_PROJECT_ID / "graph_memory" / "ainl_memory.db"
REPORT_PATH = PLUGIN_ROOT / "logs" / "repartition_report.json"


logger = logging.getLogger("repartition_by_repo")


# ── Repo discovery ────────────────────────────────────────────────────────────

def discover_repos(search_paths: Iterable[Path], max_depth: int = 3) -> List[Path]:
    """Return absolute paths of git repos beneath any search path.

    A "repo" is a directory containing a `.git` entry (file or directory).
    Walk is bounded by `max_depth` to keep this fast on large workspace dirs.
    """
    repos: List[Path] = []
    seen: set[str] = set()
    for root in search_paths:
        if not root.exists():
            continue
        root_resolved = root.resolve()
        # Manual bounded walk so we don't recurse into giant subtrees.
        stack: List[Tuple[Path, int]] = [(root_resolved, 0)]
        while stack:
            cur, depth = stack.pop()
            if depth > max_depth:
                continue
            try:
                entries = list(cur.iterdir())
            except (PermissionError, OSError):
                continue
            if any(e.name == ".git" for e in entries):
                key = str(cur)
                if key not in seen:
                    seen.add(key)
                    repos.append(cur)
                # Don't recurse into subdirs of an already-found repo (no
                # nested git repos in the common case).
                continue
            for e in entries:
                if e.is_dir() and not e.is_symlink():
                    stack.append((e, depth + 1))
    return repos


def build_path_to_repo_map(repos: List[Path]) -> Dict[str, Path]:
    """Map every repo path string to its Path. Used for prefix matching."""
    return {str(repo): repo for repo in repos}


# ── Vote engine ───────────────────────────────────────────────────────────────

def longest_prefix_match(file_path: str, repos: List[Path]) -> Optional[Path]:
    """Return the deepest repo that contains `file_path`, or None.

    `file_path` must be absolute or be resolvable against $HOME if it starts
    with `~`. Relative paths cannot be matched and return None."""
    if not file_path:
        return None
    p = Path(file_path).expanduser()
    if not p.is_absolute():
        return None
    s = str(p.resolve()) if p.exists() else str(p)
    best: Optional[Path] = None
    best_len = -1
    for repo in repos:
        repo_s = str(repo)
        if s == repo_s or s.startswith(repo_s + os.sep):
            if len(repo_s) > best_len:
                best = repo
                best_len = len(repo_s)
    return best


def vote_episode_repo(
    files_touched: List[str], repos: List[Path]
) -> Tuple[Optional[Path], Counter]:
    """Vote on the most-likely repo for an episode by counting file matches.

    Returns (winning_repo or None, full vote counter). A repo wins iff it gets
    a strict majority (>=50%) of the matched files.
    """
    votes: Counter = Counter()
    matched = 0
    for f in files_touched or []:
        repo = longest_prefix_match(f, repos)
        if repo is not None:
            votes[str(repo)] += 1
            matched += 1
    if matched == 0:
        return None, votes
    top, top_count = votes.most_common(1)[0]
    if top_count * 2 >= matched:  # >=50%
        return Path(top), votes
    return None, votes


# ── Backfill driver ───────────────────────────────────────────────────────────

class Repartitioner:
    def __init__(
        self,
        legacy_db: Path,
        repos: List[Path],
        dry_run: bool = False,
        verbose: bool = False,
        purge_legacy: bool = False,
    ):
        self.legacy_db = legacy_db
        self.repos = repos
        self.dry_run = dry_run
        self.verbose = verbose
        self.purge_legacy = purge_legacy
        # repo_path → list of (legacy_node_id, new_node_id) pairs we wrote.
        self.assignments: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        # node_id → target_repo_id, for downstream edge replication.
        self.node_to_target: Dict[str, str] = {}
        self.report = {
            "started_at": int(time.time()),
            "legacy_db": str(legacy_db),
            "repos_discovered": [str(r) for r in repos],
            "dry_run": dry_run,
            "purge_legacy": purge_legacy,
            "by_node_type": {},
            "edges": {},
            "errors": [],
        }

    # ── public ────────────────────────────────────────────────────────────

    def run(self) -> int:
        if not self.legacy_db.exists():
            print(f"Legacy DB not found at {self.legacy_db} — nothing to backfill.")
            return 0

        # Safety net: snapshot the legacy DB (and its WAL/SHM siblings)
        # BEFORE we touch anything. The repartition writes to per-repo DBs
        # *and* mutates the legacy metadata column on every replicated
        # node, so a mid-run crash or bad target-repo discovery could
        # leave the legacy bucket in a partial state. The snapshot is
        # always made — even on dry-run we record the path that would be
        # used so reports are reproducible.
        backup_info = self._backup_legacy_db()
        self.report["legacy_db_backup"] = backup_info

        with sqlite3.connect(str(self.legacy_db)) as legacy_conn:
            legacy_conn.row_factory = sqlite3.Row
            self._partition_episodes(legacy_conn)
            self._partition_failures(legacy_conn)
            self._partition_semantics(legacy_conn)
            self._partition_procedurals(legacy_conn)
            # Persona + Goal: keep in legacy by design.
            self.report["by_node_type"]["persona"] = {
                "kept_in_legacy": self._count_type(legacy_conn, "persona"),
                "moved": 0,
                "note": "Persona is global by design.",
            }
            self.report["by_node_type"]["goal"] = {
                "kept_in_legacy": self._count_type(legacy_conn, "goal"),
                "moved": 0,
                "note": "Goals are global until users explicitly opt-in.",
            }
            # Runtime state is dropped on backfill (per-project state has no
            # meaning after re-key).
            self.report["by_node_type"]["runtime_state"] = {
                "kept_in_legacy": self._count_type(legacy_conn, "runtime_state"),
                "moved": 0,
                "note": "RUNTIME_STATE intentionally not migrated — re-keying invalidates it.",
            }

            self._replicate_edges(legacy_conn)

            if self.purge_legacy and not self.dry_run:
                self._purge_migrated_nodes(legacy_conn)

        self._write_report()
        return 0

    # ── per-type partitioners ─────────────────────────────────────────────

    def _partition_episodes(self, legacy_conn: sqlite3.Connection) -> None:
        rows = list(self._iter_nodes(legacy_conn, "episode"))
        moved = 0
        kept = 0
        no_files = 0
        no_majority = 0
        for row in rows:
            data = json.loads(row["data"]) if row["data"] else {}
            files = data.get("files_touched") or []
            if not files:
                no_files += 1
                kept += 1
                continue
            winner, votes = vote_episode_repo(files, self.repos)
            if winner is None:
                no_majority += 1
                kept += 1
                if self.verbose:
                    print(f"  episode {row['id']}: no majority ({dict(votes)})")
                continue
            target_id = _hash_anchor(winner)
            self._replicate_node(row, target_id, winner)
            moved += 1
        self.report["by_node_type"]["episode"] = {
            "total": len(rows),
            "moved": moved,
            "kept_in_legacy": kept,
            "skipped_no_files": no_files,
            "skipped_no_majority": no_majority,
        }

    def _partition_failures(self, legacy_conn: sqlite3.Connection) -> None:
        rows = list(self._iter_nodes(legacy_conn, "failure"))
        moved = 0
        kept = 0
        for row in rows:
            data = json.loads(row["data"]) if row["data"] else {}
            f = data.get("file")
            if not f:
                kept += 1
                continue
            winner = longest_prefix_match(f, self.repos)
            if winner is None:
                kept += 1
                continue
            target_id = _hash_anchor(winner)
            self._replicate_node(row, target_id, winner)
            moved += 1
        self.report["by_node_type"]["failure"] = {
            "total": len(rows),
            "moved": moved,
            "kept_in_legacy": kept,
        }

    def _partition_semantics(self, legacy_conn: sqlite3.Connection) -> None:
        # Inherit repo from source episode via DERIVES_FROM edge.
        rows = list(self._iter_nodes(legacy_conn, "semantic"))
        moved = 0
        kept = 0
        for row in rows:
            target_node_ids = self._neighbors(legacy_conn, row["id"], "DERIVES_FROM")
            target_repo_id: Optional[str] = None
            for tid in target_node_ids:
                tr = self.node_to_target.get(tid)
                if tr is not None:
                    target_repo_id = tr
                    break
            if target_repo_id is None:
                kept += 1
                continue
            target_repo = next(
                (r for r in self.repos if _hash_anchor(r) == target_repo_id), None
            )
            if target_repo is None:
                kept += 1
                continue
            self._replicate_node(row, target_repo_id, target_repo)
            moved += 1
        self.report["by_node_type"]["semantic"] = {
            "total": len(rows),
            "moved": moved,
            "kept_in_legacy": kept,
        }

    def _partition_procedurals(self, legacy_conn: sqlite3.Connection) -> None:
        rows = list(self._iter_nodes(legacy_conn, "procedural"))
        moved = 0
        kept = 0
        for row in rows:
            data = json.loads(row["data"]) if row["data"] else {}
            evidence: List[str] = data.get("evidence_ids") or []
            votes: Counter = Counter()
            for eid in evidence:
                tr = self.node_to_target.get(eid)
                if tr is not None:
                    votes[tr] += 1
            if not votes:
                kept += 1
                continue
            target_repo_id, top_count = votes.most_common(1)[0]
            if top_count * 2 < sum(votes.values()):
                kept += 1
                continue
            target_repo = next(
                (r for r in self.repos if _hash_anchor(r) == target_repo_id), None
            )
            if target_repo is None:
                kept += 1
                continue
            self._replicate_node(row, target_repo_id, target_repo)
            moved += 1
        self.report["by_node_type"]["procedural"] = {
            "total": len(rows),
            "moved": moved,
            "kept_in_legacy": kept,
        }

    # ── edge replication ──────────────────────────────────────────────────

    def _replicate_edges(self, legacy_conn: sqlite3.Connection) -> None:
        cur = legacy_conn.execute("SELECT * FROM ainl_graph_edges")
        replicated = 0
        cross_repo = 0
        legacy_only = 0
        for edge in cur:
            from_target = self.node_to_target.get(edge["from_node"])
            to_target = self.node_to_target.get(edge["to_node"])
            if from_target is None or to_target is None:
                legacy_only += 1
                continue
            if from_target != to_target:
                cross_repo += 1
                if self.verbose:
                    print(
                        f"  edge {edge['id']} crosses repos "
                        f"({from_target[:8]} → {to_target[:8]}): dropping"
                    )
                continue
            target_repo = next(
                (r for r in self.repos if _hash_anchor(r) == from_target), None
            )
            if target_repo is None:
                legacy_only += 1
                continue
            self._write_edge_to_repo(edge, target_repo, from_target)
            replicated += 1
        self.report["edges"] = {
            "replicated": replicated,
            "dropped_cross_repo": cross_repo,
            "kept_in_legacy_only": legacy_only,
        }

    # ── helpers ───────────────────────────────────────────────────────────

    def _iter_nodes(self, conn: sqlite3.Connection, node_type: str) -> Iterable[sqlite3.Row]:
        # Skip nodes already migrated by a prior run (idempotency).
        cur = conn.execute(
            "SELECT * FROM ainl_graph_nodes WHERE node_type = ? AND project_id = ?",
            (node_type, LEGACY_GLOBAL_PROJECT_ID),
        )
        for row in cur:
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
            if metadata.get("repartitioned_to"):
                continue
            yield row

    def _count_type(self, conn: sqlite3.Connection, node_type: str) -> int:
        return conn.execute(
            "SELECT COUNT(*) FROM ainl_graph_nodes WHERE node_type = ? AND project_id = ?",
            (node_type, LEGACY_GLOBAL_PROJECT_ID),
        ).fetchone()[0]

    def _neighbors(
        self, conn: sqlite3.Connection, node_id: str, edge_type: str
    ) -> List[str]:
        rows = conn.execute(
            "SELECT to_node FROM ainl_graph_edges WHERE from_node = ? AND edge_type = ?",
            (node_id, edge_type),
        ).fetchall()
        return [r["to_node"] for r in rows]

    def _replicate_node(
        self, row: sqlite3.Row, target_repo_id: str, target_repo: Path
    ) -> None:
        if self.verbose:
            print(
                f"  {row['node_type']} {row['id']} → {target_repo_id[:8]} ({target_repo})"
            )
        self.node_to_target[row["id"]] = target_repo_id
        self.assignments[target_repo_id].append((row["id"], row["id"]))
        if self.dry_run:
            return
        target_db = self._ensure_target_db(target_repo_id)
        with sqlite3.connect(str(target_db)) as conn:
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
            metadata["backfilled_from_legacy"] = LEGACY_GLOBAL_PROJECT_ID
            metadata["backfilled_at"] = int(time.time())
            conn.execute(
                """
                INSERT OR REPLACE INTO ainl_graph_nodes
                (id, node_type, project_id, agent_id, created_at, updated_at,
                 confidence, data, metadata, embedding_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["node_type"],
                    target_repo_id,
                    row["agent_id"],
                    row["created_at"],
                    int(time.time()),
                    row["confidence"],
                    row["data"],
                    json.dumps(metadata),
                    row["embedding_text"],
                ),
            )
            conn.commit()
        # Mark legacy node as repartitioned (no delete unless --purge-legacy).
        with sqlite3.connect(str(self.legacy_db)) as legacy_conn:
            legacy_meta = json.loads(row["metadata"]) if row["metadata"] else {}
            legacy_meta["repartitioned_to"] = target_repo_id
            legacy_conn.execute(
                "UPDATE ainl_graph_nodes SET metadata = ? WHERE id = ?",
                (json.dumps(legacy_meta), row["id"]),
            )
            legacy_conn.commit()

    def _write_edge_to_repo(
        self, edge: sqlite3.Row, target_repo: Path, target_repo_id: str
    ) -> None:
        if self.dry_run:
            return
        target_db = self._ensure_target_db(target_repo_id)
        with sqlite3.connect(str(target_db)) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO ainl_graph_edges
                (id, edge_type, from_node, to_node, project_id, created_at,
                 confidence, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edge["id"],
                    edge["edge_type"],
                    edge["from_node"],
                    edge["to_node"],
                    target_repo_id,
                    edge["created_at"],
                    edge["confidence"],
                    edge["metadata"],
                ),
            )
            conn.commit()

    def _purge_migrated_nodes(self, conn: sqlite3.Connection) -> None:
        cur = conn.execute(
            """
            SELECT id FROM ainl_graph_nodes
            WHERE project_id = ?
              AND json_extract(metadata, '$.repartitioned_to') IS NOT NULL
            """,
            (LEGACY_GLOBAL_PROJECT_ID,),
        )
        ids = [r["id"] for r in cur]
        if not ids:
            return
        # Delete in chunks to avoid SQL parameter limits.
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            placeholders = ",".join("?" * len(chunk))
            conn.execute(
                f"DELETE FROM ainl_graph_nodes WHERE id IN ({placeholders})",
                chunk,
            )
        conn.commit()
        self.report["legacy_purged"] = len(ids)

    def _ensure_target_db(self, target_repo_id: str) -> Path:
        target_dir = PROJECTS_ROOT / target_repo_id / "graph_memory"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_db = target_dir / "ainl_memory.db"
        if not target_db.exists():
            schema_path = PLUGIN_ROOT / "mcp_server" / "schema.sql"
            schema = schema_path.read_text()
            with sqlite3.connect(str(target_db)) as conn:
                conn.executescript(schema)
        return target_db

    def _backup_legacy_db(self) -> Dict[str, Any]:
        """Snapshot the legacy global DB + WAL/SHM siblings before any write.

        Returns a record with ``files`` (list of {src, dst, bytes}) and
        ``errors``. Errors are non-fatal in dry-run mode, but in a real
        run a backup failure aborts the repartition.
        """
        ts = datetime.fromtimestamp(self.report["started_at"], tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        suffix = f".repartition-backup.{ts}"
        sources = [self.legacy_db]
        for sfx in ("-wal", "-shm"):
            side = Path(str(self.legacy_db) + sfx)
            if side.exists():
                sources.append(side)
        record: Dict[str, Any] = {
            "timestamp": ts,
            "dry_run": self.dry_run,
            "files": [],
            "errors": [],
        }
        for src in sources:
            dst = src.with_suffix(src.suffix + suffix)
            if self.dry_run:
                record["files"].append({"src": str(src), "dst": str(dst), "bytes": None, "would_copy": True})
                continue
            try:
                shutil.copy2(src, dst)
                record["files"].append({"src": str(src), "dst": str(dst), "bytes": dst.stat().st_size})
            except OSError as e:
                record["errors"].append({"src": str(src), "error": str(e)})
        if record["errors"] and not self.dry_run:
            raise RuntimeError(
                f"Failed to back up legacy DB before repartition: {record['errors']}"
            )
        return record

    def _write_report(self) -> None:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.report["finished_at"] = int(time.time())
        REPORT_PATH.write_text(json.dumps(self.report, indent=2))
        print(f"Wrote report → {REPORT_PATH}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Plan only; no writes.")
    parser.add_argument("--report", action="store_true", help="Verbose per-node decisions.")
    parser.add_argument(
        "--purge-legacy",
        action="store_true",
        help="After successful migration, delete the legacy nodes that were moved.",
    )
    parser.add_argument(
        "--legacy-db",
        type=Path,
        default=LEGACY_DB_PATH,
        help=f"Path to the legacy global DB (default: {LEGACY_DB_PATH})",
    )
    parser.add_argument(
        "--search-paths",
        nargs="+",
        type=Path,
        default=DEFAULT_SEARCH_PATHS,
        help="Workspace dirs to walk when discovering repos.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if not args.report else logging.DEBUG,
        format="%(message)s",
    )

    print(f"Discovering repos under: {[str(p) for p in args.search_paths]}")
    repos = discover_repos(args.search_paths)
    print(f"Found {len(repos)} git repos.")
    if args.report:
        for r in repos:
            print(f"  {_hash_anchor(r)[:8]}  {r}")

    rp = Repartitioner(
        legacy_db=args.legacy_db,
        repos=repos,
        dry_run=args.dry_run,
        verbose=args.report,
        purge_legacy=args.purge_legacy,
    )
    rc = rp.run()

    print(json.dumps(rp.report, indent=2))
    return rc


if __name__ == "__main__":
    sys.exit(main())
