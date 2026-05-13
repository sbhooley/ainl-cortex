"""
Memory reconciliation — detects and corrects stale environment references in graph memory.

Runs at SessionStart for the Python backend. The Rust twin (reconcile_environment in
ainl_native/src/reconcile.rs) runs when store_backend = "native".

Design principles:
  - One canonical snapshot node per project, identified by a STABLE UUID derived from
    project_id via uuid5. write_node() is upsert-by-ID, so there is never more than
    one active snapshot and stale nodes never accumulate.
  - O(1) lookup: get_node(stable_id) instead of FTS (FTS searches embedding_text, which
    does not contain the internal tag string).
  - Path normalization via Path.resolve() before comparison so symlinks and trailing
    slashes never produce false positives.
  - Always non-fatal: every exception is caught and logged at DEBUG.
"""

import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_ENV_CLUSTER = "environment_snapshot"
# _STALE_CLUSTER kept for recognising old-format stale nodes written by pre-fix code.
_STALE_CLUSTER = "environment_snapshot:stale"
_LEGACY_CLUSTER = "environment_snapshot:legacy"


# ── Stable node identity ──────────────────────────────────────────────────────

def _snapshot_node_id(project_id: str) -> str:
    """Deterministic UUID for this project's env snapshot — always the same ID.

    Using uuid5 (SHA-1 namespace hash) guarantees exactly one snapshot node
    per project regardless of how many sessions have run. write_node() is an
    upsert, so the node is updated in place rather than duplicated.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"env_snapshot:{project_id}"))


# ── Environment capture ───────────────────────────────────────────────────────

def _normalize_root(plugin_root: str) -> str:
    """Resolve symlinks and canonicalize separators so comparison is path-stable."""
    try:
        return str(Path(plugin_root).resolve())
    except Exception:
        return str(Path(plugin_root))


def _current_env(plugin_root: str, config_backend: str) -> Dict[str, Any]:
    root = _normalize_root(plugin_root)
    return {
        "plugin_root": root,
        "plugin_name": Path(root).name,
        "config_backend": config_backend,
    }


def _fact_str(env: Dict[str, Any]) -> str:
    return (
        f"environment_snapshot plugin_reference: "
        f"plugin={env['plugin_name']} path={env['plugin_root']} backend={env['config_backend']}"
    )


# ── Snapshot read / write ─────────────────────────────────────────────────────

def _find_snapshot(store, project_id: str):
    """O(1) lookup by stable UUID.

    Validates the returned node is actually an env snapshot
    (topic_cluster guard prevents acting on a highly unlikely UUID collision).
    Returns None if not yet written or if the node has been invalidated.
    """
    try:
        node = store.get_node(_snapshot_node_id(project_id))
        if node is None:
            return None
        data = node.data if isinstance(node.data, dict) else {}
        if data.get("topic_cluster") == _ENV_CLUSTER:
            return node
    except Exception as e:
        logger.debug("env snapshot lookup failed: %s", e)
    return None


def _write_snapshot(
    store,
    project_id: str,
    env: Dict[str, Any],
    prev_changes: Optional[List[str]] = None,
) -> str:
    """Write (or overwrite) the canonical env snapshot node for this project.

    Uses the stable UUID so this is always an in-place upsert.
    """
    from node_types import GraphNode, NodeType

    now = int(time.time())
    node_id = _snapshot_node_id(project_id)
    fact = _fact_str(env)

    meta: Dict[str, Any] = {
        **env,
        "snapshot_type": "environment",
        "captured_at": now,
    }
    if prev_changes:
        meta["last_change"] = {"changes": prev_changes, "changed_at": now}

    node = GraphNode(
        id=node_id,
        node_type=NodeType.SEMANTIC,
        project_id=project_id,
        created_at=now,
        updated_at=now,
        confidence=1.0,
        data={
            "fact": fact,
            "topic_cluster": _ENV_CLUSTER,
            "tags": ["auto_env_snapshot", "plugin_reference", "environment"],
            "recurrence_count": 1,
            "reference_count": 0,
            "source_turn_id": None,
        },
        metadata=meta,
        embedding_text=fact,
    )
    store.write_node(node)
    return node_id


# ── Legacy cleanup ────────────────────────────────────────────────────────────

def _cleanup_legacy_snapshots(store, project_id: str, keep_id: str) -> None:
    """One-time cleanup of phantom snapshot nodes written by pre-fix code.

    The old code wrote one new-UUID snapshot per session (because FTS never
    found the previous one). Those nodes are harmless but waste space. We mark
    them as legacy so they're excluded from all future snapshot lookups.

    Only runs when no stable-UUID snapshot exists yet (i.e., exactly once per
    project, on the first session after upgrading to the fixed code).
    """
    try:
        from node_types import NodeType
        nodes = store.query_by_type(NodeType.SEMANTIC, project_id, limit=500, min_confidence=0.0)
        for node in nodes:
            data = node.data if isinstance(node.data, dict) else {}
            tc = data.get("topic_cluster", "")
            if tc in (_ENV_CLUSTER, _STALE_CLUSTER) and node.id != keep_id:
                store.update_node_data(node.id, {"topic_cluster": _LEGACY_CLUSTER})
        logger.debug("Legacy env snapshot cleanup complete for project %s", project_id[:8])
    except Exception as e:
        logger.debug("Legacy snapshot cleanup failed (non-fatal): %s", e)


# ── Public API ────────────────────────────────────────────────────────────────

def reconcile(
    store,
    project_id: str,
    plugin_root: str,
    config_backend: str,
) -> Dict[str, Any]:
    """Compare the stored environment snapshot against the current environment.

    Returns {stale_found: bool, changes: [str], snapshot_id: str}.

    stale_found is True only when actual mismatches are detected and corrected.
    Always non-fatal — any internal exception returns stale_found=False so the
    SessionStart hook is never blocked.
    """
    try:
        current = _current_env(plugin_root, config_backend)
        existing = _find_snapshot(store, project_id)
        changes: List[str] = []

        if existing is None:
            # First run with fixed code: clean up any phantom nodes from old code.
            _cleanup_legacy_snapshots(store, project_id, _snapshot_node_id(project_id))
        else:
            stored = existing.metadata or {}
            stored_name = stored.get("plugin_name", "")
            stored_root = stored.get("plugin_root", "")
            stored_backend = stored.get("config_backend", "")

            if stored_name and stored_name != current["plugin_name"]:
                changes.append(f"plugin renamed: {stored_name} → {current['plugin_name']}")
            if stored_root and stored_root != current["plugin_root"]:
                changes.append(f"plugin path changed: {stored_root} → {current['plugin_root']}")
            if stored_backend and stored_backend != current["config_backend"]:
                changes.append(f"backend changed: {stored_backend} → {current['config_backend']}")

        snapshot_id: str
        if existing is None or changes:
            snapshot_id = _write_snapshot(store, project_id, current, changes or None)
        else:
            snapshot_id = existing.id

        return {
            "stale_found": bool(changes),
            "changes": changes,
            "snapshot_id": snapshot_id,
        }

    except Exception as e:
        logger.debug("reconcile failed (non-fatal): %s", e)
        return {"stale_found": False, "changes": [], "snapshot_id": ""}
