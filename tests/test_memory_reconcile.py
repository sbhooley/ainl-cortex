"""
Tests for mcp_server/memory_reconcile.py

Covers:
  - Stable UUID derivation (same for same project_id, different across projects)
  - First run: no snapshot → written, stale_found=False
  - Idempotent: same env twice → no write on second call, stale_found=False
  - Plugin rename detection
  - Plugin path change detection
  - Backend change detection
  - Multiple simultaneous changes
  - Path normalization (trailing slash, symlink-equivalent paths)
  - Legacy snapshot cleanup (old random-UUID nodes marked as legacy on first upgrade run)
  - Store error → non-fatal, returns stale_found=False
  - Native backend (NativeGraphStore) routing — skipped when ainl_native not built
"""

import sys
import uuid
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))

from mcp_server.graph_store import SQLiteGraphStore
from mcp_server.node_types import GraphNode, NodeType
from mcp_server.memory_reconcile import (
    _snapshot_node_id,
    _normalize_root,
    _current_env,
    _find_snapshot,
    _write_snapshot,
    _cleanup_legacy_snapshots,
    _ENV_CLUSTER,
    _STALE_CLUSTER,
    _LEGACY_CLUSTER,
    reconcile,
)

PROJECT_A = "aaaa1111bbbb2222"
PROJECT_B = "cccc3333dddd4444"


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db():
    with NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    store = SQLiteGraphStore(db_path)
    yield store, db_path
    db_path.unlink(missing_ok=True)


@pytest.fixture
def tmp_dir():
    with TemporaryDirectory() as d:
        yield Path(d)


# ── _snapshot_node_id ─────────────────────────────────────────────────────────

def test_snapshot_id_is_stable():
    id1 = _snapshot_node_id(PROJECT_A)
    id2 = _snapshot_node_id(PROJECT_A)
    assert id1 == id2


def test_snapshot_id_differs_across_projects():
    assert _snapshot_node_id(PROJECT_A) != _snapshot_node_id(PROJECT_B)


def test_snapshot_id_is_valid_uuid():
    raw = _snapshot_node_id(PROJECT_A)
    parsed = uuid.UUID(raw)  # raises if invalid
    assert str(parsed) == raw


# ── _normalize_root ───────────────────────────────────────────────────────────

def test_normalize_strips_trailing_slash(tmp_dir):
    with_slash = str(tmp_dir) + "/"
    without_slash = str(tmp_dir)
    assert _normalize_root(with_slash) == _normalize_root(without_slash)


def test_normalize_resolves_symlink(tmp_dir):
    real = tmp_dir / "real_plugin"
    real.mkdir()
    link = tmp_dir / "link_plugin"
    link.symlink_to(real)
    assert _normalize_root(str(real)) == _normalize_root(str(link))


def test_normalize_nonexistent_path_does_not_raise():
    result = _normalize_root("/nonexistent/path/to/plugin/")
    assert result == "/nonexistent/path/to/plugin"


# ── first run ─────────────────────────────────────────────────────────────────

def test_first_run_writes_snapshot_and_returns_no_stale(tmp_db, tmp_dir):
    store, _ = tmp_db
    plugin_root = str(tmp_dir / "ainl-cortex")
    Path(plugin_root).mkdir()

    result = reconcile(store, PROJECT_A, plugin_root, "python")

    assert result["stale_found"] is False
    assert result["changes"] == []
    assert result["snapshot_id"] == _snapshot_node_id(PROJECT_A)

    # Node must be persisted
    node = store.get_node(_snapshot_node_id(PROJECT_A))
    assert node is not None
    assert node.data["topic_cluster"] == _ENV_CLUSTER
    assert node.data["fact"].startswith("environment_snapshot plugin_reference:")
    assert node.metadata["plugin_name"] == "ainl-cortex"
    assert node.metadata["config_backend"] == "python"


# ── idempotency ───────────────────────────────────────────────────────────────

def test_second_run_same_env_does_not_report_stale(tmp_db, tmp_dir):
    store, _ = tmp_db
    plugin_root = str(tmp_dir / "ainl-cortex")
    Path(plugin_root).mkdir()

    reconcile(store, PROJECT_A, plugin_root, "python")
    result = reconcile(store, PROJECT_A, plugin_root, "python")

    assert result["stale_found"] is False
    assert result["changes"] == []


def test_second_run_does_not_duplicate_node(tmp_db, tmp_dir):
    store, _ = tmp_db
    plugin_root = str(tmp_dir / "ainl-cortex")
    Path(plugin_root).mkdir()

    reconcile(store, PROJECT_A, plugin_root, "python")
    reconcile(store, PROJECT_A, plugin_root, "python")

    # There must be exactly one non-legacy snapshot node
    nodes = store.query_by_type(NodeType.SEMANTIC, PROJECT_A, limit=100, min_confidence=0.0)
    env_nodes = [n for n in nodes if n.data.get("topic_cluster") == _ENV_CLUSTER]
    assert len(env_nodes) == 1


# ── plugin rename detection ───────────────────────────────────────────────────

def test_detects_plugin_rename(tmp_db, tmp_dir):
    store, _ = tmp_db
    old_root = tmp_dir / "ainl-graph-memory"
    old_root.mkdir()
    new_root = tmp_dir / "ainl-cortex"
    new_root.mkdir()

    reconcile(store, PROJECT_A, str(old_root), "python")
    result = reconcile(store, PROJECT_A, str(new_root), "python")

    assert result["stale_found"] is True
    assert any("ainl-graph-memory" in c and "ainl-cortex" in c for c in result["changes"])


def test_after_rename_snapshot_updated(tmp_db, tmp_dir):
    store, _ = tmp_db
    old_root = tmp_dir / "ainl-graph-memory"
    old_root.mkdir()
    new_root = tmp_dir / "ainl-cortex"
    new_root.mkdir()

    reconcile(store, PROJECT_A, str(old_root), "python")
    reconcile(store, PROJECT_A, str(new_root), "python")

    node = store.get_node(_snapshot_node_id(PROJECT_A))
    assert node.metadata["plugin_name"] == "ainl-cortex"
    assert node.metadata["plugin_root"] == _normalize_root(str(new_root))


def test_after_rename_stable_id_unchanged(tmp_db, tmp_dir):
    store, _ = tmp_db
    old_root = tmp_dir / "ainl-graph-memory"
    old_root.mkdir()
    new_root = tmp_dir / "ainl-cortex"
    new_root.mkdir()

    r1 = reconcile(store, PROJECT_A, str(old_root), "python")
    r2 = reconcile(store, PROJECT_A, str(new_root), "python")

    assert r1["snapshot_id"] == r2["snapshot_id"] == _snapshot_node_id(PROJECT_A)


# ── path change detection ─────────────────────────────────────────────────────

def test_detects_path_change(tmp_db, tmp_dir):
    store, _ = tmp_db
    path_a = tmp_dir / "home_a" / "ainl-cortex"
    path_b = tmp_dir / "home_b" / "ainl-cortex"
    path_a.mkdir(parents=True)
    path_b.mkdir(parents=True)

    reconcile(store, PROJECT_A, str(path_a), "python")
    result = reconcile(store, PROJECT_A, str(path_b), "python")

    assert result["stale_found"] is True
    assert any("plugin path changed" in c for c in result["changes"])


# ── backend change detection ──────────────────────────────────────────────────

def test_detects_backend_change(tmp_db, tmp_dir):
    store, _ = tmp_db
    plugin_root = str(tmp_dir / "ainl-cortex")
    Path(plugin_root).mkdir()

    reconcile(store, PROJECT_A, plugin_root, "python")
    result = reconcile(store, PROJECT_A, plugin_root, "native")

    assert result["stale_found"] is True
    assert any("backend changed" in c for c in result["changes"])


# ── multiple changes ──────────────────────────────────────────────────────────

def test_detects_multiple_changes(tmp_db, tmp_dir):
    store, _ = tmp_db
    old_root = tmp_dir / "ainl-graph-memory"
    old_root.mkdir()
    new_root = tmp_dir / "ainl-cortex"
    new_root.mkdir()

    reconcile(store, PROJECT_A, str(old_root), "python")
    result = reconcile(store, PROJECT_A, str(new_root), "native")

    assert result["stale_found"] is True
    assert len(result["changes"]) >= 2  # rename + backend change


# ── projects are isolated ─────────────────────────────────────────────────────

def test_projects_do_not_interfere(tmp_db, tmp_dir):
    store, _ = tmp_db
    root_a = tmp_dir / "ainl-cortex"
    root_a.mkdir()

    reconcile(store, PROJECT_A, str(root_a), "python")

    # PROJECT_B has no snapshot yet; must not borrow PROJECT_A's data
    result_b = reconcile(store, PROJECT_B, str(root_a), "python")
    assert result_b["stale_found"] is False  # first run for B


# ── legacy cleanup ────────────────────────────────────────────────────────────

def _insert_old_snapshot(store, project_id: str, plugin_name: str) -> str:
    """Simulate a snapshot written by pre-fix code (random UUID)."""
    import time
    node_id = str(uuid.uuid4())
    fact = f"environment_snapshot plugin_reference: plugin={plugin_name} path=/some/path backend=python"
    store.write_node(GraphNode(
        id=node_id,
        node_type=NodeType.SEMANTIC,
        project_id=project_id,
        created_at=int(time.time()),
        updated_at=int(time.time()),
        confidence=1.0,
        data={
            "fact": fact,
            "topic_cluster": _ENV_CLUSTER,
            "tags": ["auto_env_snapshot"],
            "recurrence_count": 1,
            "reference_count": 0,
            "source_turn_id": None,
        },
        metadata={"plugin_name": plugin_name, "plugin_root": "/some/path", "config_backend": "python"},
        embedding_text=fact,
    ))
    return node_id


def test_legacy_snapshots_cleaned_up_on_first_run(tmp_db, tmp_dir):
    store, _ = tmp_db
    plugin_root = str(tmp_dir / "ainl-cortex")
    Path(plugin_root).mkdir()

    # Simulate 3 phantom nodes from old code
    legacy_ids = [_insert_old_snapshot(store, PROJECT_A, "ainl-cortex") for _ in range(3)]

    # First run with new code: should clean them up
    result = reconcile(store, PROJECT_A, plugin_root, "python")
    assert result["stale_found"] is False  # first run, no prior stable snapshot

    # Legacy nodes must be relabelled, not deleted
    for lid in legacy_ids:
        node = store.get_node(lid)
        assert node is not None, "Legacy node must still exist"
        assert node.data.get("topic_cluster") == _LEGACY_CLUSTER


def test_legacy_cleanup_does_not_run_on_subsequent_sessions(tmp_db, tmp_dir):
    store, _ = tmp_db
    plugin_root = str(tmp_dir / "ainl-cortex")
    Path(plugin_root).mkdir()

    # First run writes stable snapshot
    reconcile(store, PROJECT_A, plugin_root, "python")

    # Insert a legacy node AFTER first run (edge case)
    legacy_id = _insert_old_snapshot(store, PROJECT_A, "ainl-cortex")

    # Second run: stable snapshot exists, cleanup should NOT fire
    reconcile(store, PROJECT_A, plugin_root, "python")

    # Legacy node must still have ENV_CLUSTER (cleanup didn't run)
    node = store.get_node(legacy_id)
    assert node.data.get("topic_cluster") == _ENV_CLUSTER


# ── change history persistence ────────────────────────────────────────────────

def test_change_history_stored_in_metadata(tmp_db, tmp_dir):
    store, _ = tmp_db
    old_root = tmp_dir / "ainl-graph-memory"
    old_root.mkdir()
    new_root = tmp_dir / "ainl-cortex"
    new_root.mkdir()

    reconcile(store, PROJECT_A, str(old_root), "python")
    reconcile(store, PROJECT_A, str(new_root), "python")

    node = store.get_node(_snapshot_node_id(PROJECT_A))
    assert "last_change" in node.metadata
    assert node.metadata["last_change"]["changes"]
    assert node.metadata["last_change"]["changed_at"] > 0


# ── non-fatal error handling ──────────────────────────────────────────────────

def test_store_error_returns_non_fatal():
    class BrokenStore:
        def get_node(self, _):
            raise RuntimeError("DB locked")

    result = reconcile(BrokenStore(), PROJECT_A, "/some/path", "python")
    assert result == {"stale_found": False, "changes": [], "snapshot_id": ""}


# ── native backend routing (integration, skipped if ainl_native not available) ─

try:
    import ainl_native as _ainl_native  # noqa: F401
    _NATIVE_AVAILABLE = True
except ImportError:
    _NATIVE_AVAILABLE = False


@pytest.mark.skipif(not _NATIVE_AVAILABLE, reason="ainl_native not built")
def test_rust_reconcile_first_run(tmp_dir):
    db_path = str(tmp_dir / "ainl_native.db")
    plugin_root = str(tmp_dir / "ainl-cortex")
    Path(plugin_root).mkdir()

    result = _ainl_native.reconcile_environment(
        db_path, PROJECT_A, plugin_root, "native"
    )

    assert result["stale_found"] is False
    assert result["changes"] == []
    assert result["snapshot_id"] != ""


@pytest.mark.skipif(not _NATIVE_AVAILABLE, reason="ainl_native not built")
def test_rust_reconcile_idempotent(tmp_dir):
    db_path = str(tmp_dir / "ainl_native.db")
    plugin_root = str(tmp_dir / "ainl-cortex")
    Path(plugin_root).mkdir()

    _ainl_native.reconcile_environment(db_path, PROJECT_A, plugin_root, "native")
    result = _ainl_native.reconcile_environment(db_path, PROJECT_A, plugin_root, "native")

    assert result["stale_found"] is False


@pytest.mark.skipif(not _NATIVE_AVAILABLE, reason="ainl_native not built")
def test_rust_reconcile_detects_rename(tmp_dir):
    db_path = str(tmp_dir / "ainl_native.db")
    old_root = str(tmp_dir / "ainl-graph-memory")
    new_root = str(tmp_dir / "ainl-cortex")
    Path(old_root).mkdir()
    Path(new_root).mkdir()

    _ainl_native.reconcile_environment(db_path, PROJECT_A, old_root, "native")
    result = _ainl_native.reconcile_environment(db_path, PROJECT_A, new_root, "native")

    assert result["stale_found"] is True
    assert any("ainl-graph-memory" in c and "ainl-cortex" in c for c in result["changes"])


@pytest.mark.skipif(not _NATIVE_AVAILABLE, reason="ainl_native not built")
def test_rust_reconcile_stable_id_matches_python(tmp_dir):
    """Both implementations must derive the same stable UUID for the same project_id."""
    db_path = str(tmp_dir / "ainl_native.db")
    plugin_root = str(tmp_dir / "ainl-cortex")
    Path(plugin_root).mkdir()

    result = _ainl_native.reconcile_environment(db_path, PROJECT_A, plugin_root, "native")
    assert result["snapshot_id"] == _snapshot_node_id(PROJECT_A)


@pytest.mark.skipif(not _NATIVE_AVAILABLE, reason="ainl_native not built")
def test_rust_reconcile_path_normalization(tmp_dir):
    """Trailing slash must not trigger a false positive change."""
    db_path = str(tmp_dir / "ainl_native.db")
    plugin_root = str(tmp_dir / "ainl-cortex")
    Path(plugin_root).mkdir()

    _ainl_native.reconcile_environment(db_path, PROJECT_A, plugin_root + "/", "native")
    result = _ainl_native.reconcile_environment(db_path, PROJECT_A, plugin_root, "native")

    assert result["stale_found"] is False
