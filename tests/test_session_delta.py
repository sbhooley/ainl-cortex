"""
Tests for session delta audit log:
  - Session ID lifecycle (write / read / fallback)
  - Node content hashing (determinism, sensitivity)
  - Store write interceptor (captures all writes, passes through correctly)
  - Delta file append (format, accumulation, empty-session guard)
  - Episode session_id stamping (populated, not None)
"""

import sys
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))
sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))

from shared.session_delta import (
    write_session_id,
    read_session_id,
    session_started_at,
    node_content_hash,
    wrap_store_for_delta,
    append_session_delta,
)


# ── Minimal node stub ─────────────────────────────────────────────────────────

@dataclass
class _FakeNodeType:
    value: str

@dataclass
class _FakeNode:
    id: str
    node_type: _FakeNodeType
    data: dict


def _node(nid="n1", kind="episode", data=None):
    return _FakeNode(id=nid, node_type=_FakeNodeType(kind), data=data or {"k": "v"})


# ── Session ID lifecycle ──────────────────────────────────────────────────────

def test_write_session_id_creates_file(tmp_path):
    sid = write_session_id("proj", tmp_path)
    sid_file = tmp_path / "inbox" / "proj_session_id.txt"
    assert sid_file.exists()
    assert sid_file.read_text().strip() == sid


def test_write_session_id_is_uuid(tmp_path):
    sid = write_session_id("proj", tmp_path)
    assert len(sid) == 36
    assert sid.count("-") == 4


def test_read_session_id_returns_written_value(tmp_path):
    written = write_session_id("proj", tmp_path)
    read = read_session_id("proj", tmp_path)
    assert read == written


def test_read_session_id_fallback_when_no_file(tmp_path):
    # No startup ran — must still return a valid UUID
    fallback = read_session_id("proj_missing", tmp_path)
    assert len(fallback) == 36


def test_write_session_id_overwrites_previous(tmp_path):
    sid1 = write_session_id("proj", tmp_path)
    sid2 = write_session_id("proj", tmp_path)
    assert sid1 != sid2
    assert read_session_id("proj", tmp_path) == sid2


def test_session_started_at_returns_mtime(tmp_path):
    write_session_id("proj", tmp_path)
    t = session_started_at("proj", tmp_path)
    assert abs(t - time.time()) < 5


def test_session_started_at_fallback(tmp_path):
    t = session_started_at("missing_proj", tmp_path)
    assert abs(t - time.time()) < 5


# ── Node content hashing ──────────────────────────────────────────────────────

def test_node_content_hash_deterministic():
    n = _node(data={"x": 1, "y": "hello"})
    assert node_content_hash(n) == node_content_hash(n)


def test_node_content_hash_key_order_independent():
    n1 = _node(data={"a": 1, "b": 2})
    n2 = _node(data={"b": 2, "a": 1})
    assert node_content_hash(n1) == node_content_hash(n2)


def test_node_content_hash_sensitive_to_data():
    n1 = _node(data={"x": 1})
    n2 = _node(data={"x": 2})
    assert node_content_hash(n1) != node_content_hash(n2)


def test_node_content_hash_length():
    h = node_content_hash(_node())
    assert len(h) == 16


# ── Store write interceptor ───────────────────────────────────────────────────

class _MockStore:
    def __init__(self):
        self.written = []

    def write_node(self, node):
        self.written.append(node.id)


def test_wrap_store_captures_writes():
    store = _MockStore()
    entries = []
    wrap_store_for_delta(store, entries)

    n1 = _node("id1", "episode", {"task": "fix bug"})
    n2 = _node("id2", "failure", {"error_type": "io_error"})
    store.write_node(n1)
    store.write_node(n2)

    assert len(entries) == 2
    assert entries[0]["node_id"] == "id1"
    assert entries[0]["node_type"] == "episode"
    assert len(entries[0]["content_hash"]) == 16
    assert entries[1]["node_id"] == "id2"


def test_wrap_store_passes_through_to_underlying():
    store = _MockStore()
    entries = []
    wrap_store_for_delta(store, entries)

    n = _node("id_pass")
    store.write_node(n)

    assert "id_pass" in store.written


def test_wrap_store_other_methods_unaffected():
    class _StoreWithExtra(_MockStore):
        def get_node(self, nid):
            return f"node:{nid}"

    store = _StoreWithExtra()
    entries = []
    wrap_store_for_delta(store, entries)
    assert store.get_node("x") == "node:x"


# ── Delta file append ─────────────────────────────────────────────────────────

def test_append_session_delta_creates_file(tmp_path):
    nodes = [{"node_id": "n1", "node_type": "episode", "content_hash": "abc123"}]
    append_session_delta(tmp_path, "sid-1", "proj", time.time(), nodes)
    delta_file = tmp_path / "logs" / "session_deltas.jsonl"
    assert delta_file.exists()


def test_append_session_delta_record_format(tmp_path):
    t0 = time.time()
    nodes = [{"node_id": "n1", "node_type": "episode", "content_hash": "abc"}]
    append_session_delta(tmp_path, "sid-abc", "proj_x", t0, nodes)

    record = json.loads((tmp_path / "logs" / "session_deltas.jsonl").read_text())
    assert record["session_id"] == "sid-abc"
    assert record["project_id"] == "proj_x"
    assert record["node_count"] == 1
    assert record["nodes"][0]["node_id"] == "n1"
    assert "started_at" in record
    assert "finalized_at" in record


def test_append_session_delta_accumulates(tmp_path):
    for i in range(3):
        nodes = [{"node_id": f"n{i}", "node_type": "episode", "content_hash": "x"}]
        append_session_delta(tmp_path, f"sid-{i}", "proj", time.time(), nodes)

    lines = (tmp_path / "logs" / "session_deltas.jsonl").read_text().strip().splitlines()
    assert len(lines) == 3
    sids = [json.loads(l)["session_id"] for l in lines]
    assert sids == ["sid-0", "sid-1", "sid-2"]


def test_append_session_delta_skips_empty(tmp_path):
    append_session_delta(tmp_path, "sid-empty", "proj", time.time(), [])
    delta_file = tmp_path / "logs" / "session_deltas.jsonl"
    assert not delta_file.exists()


# ── Integration: episode session_id stamped ───────────────────────────────────

def test_episode_session_id_populated(tmp_path):
    """write_episode must stamp session_id on the episode node, not leave it None."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))
    from graph_store import get_graph_store
    from node_types import NodeType

    db = tmp_path / "ainl_memory.db"

    # Write a session ID file as startup would
    sid = write_session_id("proj_ep", Path(__file__).parent.parent)

    # Minimal session_data
    session_data = {
        "tool_captures": [],
        "files_touched": set(),
        "tools_used": set(),
        "had_errors": False,
    }

    import stop as stop_mod
    store, ep_data = stop_mod.write_episode("proj_ep", session_data)

    assert ep_data["session_id"] is not None
    assert ep_data["session_id"] != "None"
    # The session_id should be the UUID we wrote (or a valid fallback UUID)
    assert len(ep_data["session_id"]) == 36
