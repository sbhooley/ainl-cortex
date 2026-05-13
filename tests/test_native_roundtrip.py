"""
Tests for native_graph_store.py Goal/RuntimeState round-trip (issue 4).

Most assertions exercise the pure-Python `_node_to_ainl` / `_ainl_to_node`
converters and the goal-index helpers — no Rust .so needed. The end-to-end
write+read tests against `AinlNativeStore` are guarded by `_NATIVE_OK` and
skip when the extension module is not built locally.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "mcp_server"))

import native_graph_store as ngs  # noqa: E402
from node_types import GraphNode, NodeType  # noqa: E402


# ── Namespace constants ──────────────────────────────────────────────────────

class TestPluginNamespace:
    def test_prefix_is_underscore_namespaced(self):
        # Must mirror the Rust constant in ainl_native/src/session.rs.
        assert ngs.PLUGIN_TOPIC_CLUSTER_PREFIX == "_plugin:"

    def test_reserved_clusters_known(self):
        assert ngs.PLUGIN_GOAL_CLUSTER == "_plugin:goal"
        assert ngs.PLUGIN_RUNTIME_STATE_CLUSTER == "_plugin:runtime_state"
        assert ngs.PLUGIN_GOAL_CLUSTER in ngs.PLUGIN_RESERVED_CLUSTERS
        assert ngs.PLUGIN_RUNTIME_STATE_CLUSTER in ngs.PLUGIN_RESERVED_CLUSTERS

    def test_is_plugin_namespaced_helper(self):
        assert ngs._is_plugin_namespaced("_plugin:goal")
        assert ngs._is_plugin_namespaced("_plugin:runtime_state")
        assert ngs._is_plugin_namespaced("_plugin:custom_extension")
        assert not ngs._is_plugin_namespaced("topic.module.feature")
        assert not ngs._is_plugin_namespaced(None)
        assert not ngs._is_plugin_namespaced("")


# ── Goal round-trip ──────────────────────────────────────────────────────────

def _goal_node() -> GraphNode:
    return GraphNode(
        id=str(uuid.uuid4()),
        node_type=NodeType.GOAL,
        project_id="proj_test_a",
        agent_id="claude-code",
        created_at=int(time.time()),
        updated_at=int(time.time()),
        confidence=0.9,
        data={
            "title": "Migrate to Rust",
            "description": "Replace Python pipeline with Rust storage",
            "status": "active",
            "contributing_episodes": ["ep1", "ep2"],
            "tags": ["migration", "rust"],
            "deadline": "2026-12-31",
        },
        metadata={},
    )


def _runtime_state_node() -> GraphNode:
    return GraphNode(
        id=str(uuid.uuid4()),
        node_type=NodeType.RUNTIME_STATE,
        project_id="proj_test_a",
        agent_id="claude-code",
        created_at=int(time.time()),
        updated_at=int(time.time()),
        confidence=1.0,
        data={
            "turn_count": 42,
            "persona_snapshot_json": '{"axis":"focused","score":0.7}',
            "active_files": ["/tmp/foo.py", "/tmp/bar.py"],
        },
        metadata={},
    )


class TestGoalRoundTrip:
    def test_goal_writes_to_plugin_namespace(self):
        node = _goal_node()
        out = ngs._node_to_ainl(node)
        assert out["node_type"]["topic_cluster"] == ngs.PLUGIN_GOAL_CLUSTER
        # Schema version stamped.
        assert out["plugin_data"]["_schema_version"] == ngs.PLUGIN_SCHEMA_VERSION
        # py_node_type retained for back-compat reads.
        assert out["plugin_data"]["py_node_type"] == "goal"

    def test_goal_round_trip_preserves_data(self):
        original = _goal_node()
        ainl_dict = ngs._node_to_ainl(original)
        decoded = ngs._ainl_to_node(ainl_dict)

        assert decoded.node_type == NodeType.GOAL
        assert decoded.id == original.id
        assert decoded.project_id == original.project_id
        # Data fields round-trip byte-exact (minus internal markers).
        for key in ("title", "description", "status", "tags",
                    "contributing_episodes", "deadline"):
            assert decoded.data.get(key) == original.data.get(key)
        # Internal markers stripped on decode.
        assert "py_node_type" not in decoded.data
        assert "_schema_version" not in decoded.data

    def test_goal_decoded_via_topic_cluster_when_py_node_type_missing(self):
        # Defensive: a row that lost its plugin_data.py_node_type but kept the
        # namespaced cluster should still decode as a Goal.
        ainl_dict = ngs._node_to_ainl(_goal_node())
        ainl_dict["plugin_data"].pop("py_node_type", None)
        decoded = ngs._ainl_to_node(ainl_dict)
        assert decoded.node_type == NodeType.GOAL


class TestRuntimeStateRoundTrip:
    def test_runtime_state_writes_to_plugin_namespace(self):
        node = _runtime_state_node()
        out = ngs._node_to_ainl(node)
        assert out["node_type"]["topic_cluster"] == ngs.PLUGIN_RUNTIME_STATE_CLUSTER
        assert out["plugin_data"]["_schema_version"] == ngs.PLUGIN_SCHEMA_VERSION
        assert out["plugin_data"]["py_node_type"] == "runtime_state"

    def test_runtime_state_round_trip_preserves_data(self):
        original = _runtime_state_node()
        ainl_dict = ngs._node_to_ainl(original)
        decoded = ngs._ainl_to_node(ainl_dict)

        assert decoded.node_type == NodeType.RUNTIME_STATE
        assert decoded.data["turn_count"] == 42
        assert decoded.data["persona_snapshot_json"] == '{"axis":"focused","score":0.7}'
        assert decoded.data["active_files"] == ["/tmp/foo.py", "/tmp/bar.py"]


# ── End-to-end write+read against the real Rust store ───────────────────────

@pytest.mark.skipif(not ngs._NATIVE_OK, reason="ainl_native extension not built")
class TestRealStoreEndToEnd:
    def test_query_by_type_semantic_skips_plugin_clusters(self, tmp_path):
        store = ngs.NativeGraphStore(tmp_path / "ainl_native.db")

        # Write one real semantic and one Goal (which is also stored as Semantic
        # with topic_cluster=_plugin:goal).
        real_semantic = GraphNode(
            id=str(uuid.uuid4()),
            node_type=NodeType.SEMANTIC,
            project_id="proj_test_filter",
            agent_id="claude-code",
            created_at=int(time.time()),
            updated_at=int(time.time()),
            confidence=0.9,
            data={"fact": "Tests pass on macOS arm64", "tags": ["ci"]},
            metadata={},
        )
        goal = GraphNode(
            id=str(uuid.uuid4()),
            node_type=NodeType.GOAL,
            project_id="proj_test_filter",
            agent_id="claude-code",
            created_at=int(time.time()),
            updated_at=int(time.time()),
            confidence=0.9,
            data={"title": "Ship v1", "status": "active"},
            metadata={},
        )
        store.write_node(real_semantic)
        store.write_node(goal)

        results = store.query_by_type(NodeType.SEMANTIC, "proj_test_filter", limit=50)
        ids = {n.id for n in results}
        assert real_semantic.id in ids
        assert goal.id not in ids, "goal must not surface as semantic"

    def test_query_goals_uses_index(self, tmp_path):
        store = ngs.NativeGraphStore(tmp_path / "ainl_native.db")
        goal = GraphNode(
            id=str(uuid.uuid4()),
            node_type=NodeType.GOAL,
            project_id="proj_test_idx",
            agent_id="claude-code",
            created_at=int(time.time()),
            updated_at=int(time.time()),
            confidence=0.9,
            data={"title": "Index test", "status": "active"},
            metadata={},
        )
        store.write_node(goal)

        # Index file written
        assert store._goal_index_path.exists()
        idx = json.loads(store._goal_index_path.read_text())
        assert goal.id in idx
        assert idx[goal.id]["project_id"] == "proj_test_idx"

        # Query returns the goal
        results = store.query_goals("proj_test_idx")
        assert any(n.id == goal.id for n in results)


# ── Goal index helpers (no Rust) ────────────────────────────────────────────

class TestGoalIndexAtomicWrite:
    def test_atomic_write_creates_file_via_replace(self, tmp_path):
        # Construct a NativeGraphStore-like shim that only uses the index
        # helpers. We can't instantiate the real class without _NATIVE_OK.
        class _Shim:
            _goal_index_path = tmp_path / "goal_index.json"
            _read_goal_index = ngs.NativeGraphStore._read_goal_index
            _write_goal_index_atomic = ngs.NativeGraphStore._write_goal_index_atomic

        shim = _Shim()
        # Initially empty
        assert _Shim._read_goal_index(shim) == {}

        # Write some entries
        sample = {
            "g1": {"id": "g1", "project_id": "p", "title": "t", "status": "active",
                   "updated_at": 1},
            "g2": {"id": "g2", "project_id": "p", "title": "u", "status": "done",
                   "updated_at": 2},
        }
        _Shim._write_goal_index_atomic(shim, sample)
        assert (tmp_path / "goal_index.json").exists()
        # No tmp file left over
        assert not (tmp_path / "goal_index.tmp").exists()

        # Re-read returns the same data
        assert _Shim._read_goal_index(shim) == sample
