"""
Tests for confidence decay and node TTL:
  - decay_node_confidence: only touches old nodes, by node type, clamped at 0
  - delete_expired_nodes: removes low-confidence old nodes, spares recent ones
  - Decay leaves episode nodes untouched
  - Config defaults applied correctly
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))

from graph_store import get_graph_store
from node_types import GraphNode, NodeType, create_semantic_node, create_failure_node


def _make_store(tmp_path):
    return get_graph_store(tmp_path / "test.db")


def _node(project_id, node_type, created_at, confidence=0.9, nid=None):
    import uuid
    return GraphNode(
        id=nid or str(uuid.uuid4()),
        node_type=node_type,
        project_id=project_id,
        agent_id="test",
        created_at=created_at,
        updated_at=created_at,
        confidence=confidence,
        data={"fact": "test fact"},
        embedding_text="test fact",
    )


OLD = int(time.time()) - 200 * 86400   # 200 days ago
RECENT = int(time.time()) - 10 * 86400  # 10 days ago
NOW = int(time.time())


# ── decay_node_confidence ────────────────────────────────────────────────────

def test_decay_reduces_old_semantic_confidence(tmp_path):
    store = _make_store(tmp_path)
    node = _node("proj", NodeType.SEMANTIC, OLD, confidence=0.9)
    store.write_node(node)
    count = store.decay_node_confidence("proj", older_than_days=90, factor=0.1)
    assert count == 1
    updated = store.get_node(node.id)
    assert abs(updated.confidence - 0.8) < 0.001


def test_decay_skips_recent_nodes(tmp_path):
    store = _make_store(tmp_path)
    node = _node("proj", NodeType.SEMANTIC, RECENT, confidence=0.9)
    store.write_node(node)
    count = store.decay_node_confidence("proj", older_than_days=90, factor=0.1)
    assert count == 0


def test_decay_skips_episode_nodes(tmp_path):
    store = _make_store(tmp_path)
    node = _node("proj", NodeType.EPISODE, OLD, confidence=1.0)
    store.write_node(node)
    count = store.decay_node_confidence("proj", older_than_days=90, factor=0.1)
    assert count == 0
    assert store.get_node(node.id).confidence == 1.0


def test_decay_clamps_at_zero(tmp_path):
    store = _make_store(tmp_path)
    node = _node("proj", NodeType.SEMANTIC, OLD, confidence=0.03)
    store.write_node(node)
    store.decay_node_confidence("proj", older_than_days=90, factor=0.1)
    updated = store.get_node(node.id)
    assert updated.confidence >= 0.0


def test_decay_respects_custom_node_types(tmp_path):
    store = _make_store(tmp_path)
    sem = _node("proj", NodeType.SEMANTIC, OLD, confidence=0.9)
    fail = _node("proj", NodeType.FAILURE, OLD, confidence=0.9)
    store.write_node(sem)
    store.write_node(fail)
    # Only decay semantic
    count = store.decay_node_confidence("proj", older_than_days=90, factor=0.1, node_types=["semantic"])
    assert count == 1
    assert abs(store.get_node(sem.id).confidence - 0.8) < 0.001
    assert abs(store.get_node(fail.id).confidence - 0.9) < 0.001


def test_decay_isolated_by_project(tmp_path):
    store = _make_store(tmp_path)
    n1 = _node("proj_a", NodeType.SEMANTIC, OLD, confidence=0.9)
    n2 = _node("proj_b", NodeType.SEMANTIC, OLD, confidence=0.9)
    store.write_node(n1)
    store.write_node(n2)
    store.decay_node_confidence("proj_a", older_than_days=90, factor=0.1)
    assert abs(store.get_node(n1.id).confidence - 0.8) < 0.001
    assert abs(store.get_node(n2.id).confidence - 0.9) < 0.001


# ── delete_expired_nodes ──────────────────────────────────────────────────────

def test_delete_removes_old_low_confidence(tmp_path):
    store = _make_store(tmp_path)
    node = _node("proj", NodeType.SEMANTIC, OLD, confidence=0.04)
    store.write_node(node)
    deleted = store.delete_expired_nodes("proj", ttl_days=90, min_confidence=0.05)
    assert deleted == 1
    assert store.get_node(node.id) is None


def test_delete_spares_recent_low_confidence(tmp_path):
    store = _make_store(tmp_path)
    node = _node("proj", NodeType.SEMANTIC, RECENT, confidence=0.01)
    store.write_node(node)
    deleted = store.delete_expired_nodes("proj", ttl_days=90, min_confidence=0.05)
    assert deleted == 0
    assert store.get_node(node.id) is not None


def test_delete_spares_high_confidence_old_nodes(tmp_path):
    store = _make_store(tmp_path)
    node = _node("proj", NodeType.SEMANTIC, OLD, confidence=0.8)
    store.write_node(node)
    deleted = store.delete_expired_nodes("proj", ttl_days=90, min_confidence=0.05)
    assert deleted == 0


def test_delete_never_touches_episodes(tmp_path):
    store = _make_store(tmp_path)
    node = _node("proj", NodeType.EPISODE, OLD, confidence=0.01)
    store.write_node(node)
    deleted = store.delete_expired_nodes("proj", ttl_days=90, min_confidence=0.05)
    assert deleted == 0
    assert store.get_node(node.id) is not None
