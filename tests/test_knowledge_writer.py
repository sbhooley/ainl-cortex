"""Integration tests for knowledge_writer ingest + dedup."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _path():
    import sys

    for p in (
        str(PLUGIN_ROOT / "tests"),
        str(PLUGIN_ROOT / "mcp_server"),
        str(PLUGIN_ROOT / "hooks"),
    ):
        if p not in sys.path:
            sys.path.insert(0, p)


def _bind_store(monkeypatch, project_id: str, db: Path):
    from knowledge_test_util import bind_test_graph_store

    return bind_test_graph_store(monkeypatch, project_id, db)


def test_ingest_facts_dedup_and_fts(tmp_path, monkeypatch):
    from graph_store import get_graph_store
    from knowledge_writer import ingest_facts
    from node_types import NodeType, semantic_content_id

    project_id = "testproj12345678"
    db = tmp_path / "ainl_memory.db"
    store = _bind_store(monkeypatch, project_id, db)
    fact = "LinkedIn golden 60-minute window drives reach for vertical video"
    r1 = ingest_facts(
        project_id,
        [fact],
        source_kind="artifact",
        source_ref="/tmp/doc.md",
        tags=["research"],
        store=store,
    )
    assert r1["written"] == 1

    r2 = ingest_facts(
        project_id,
        [fact],
        source_kind="artifact",
        source_ref="/tmp/doc.md",
        tags=["research"],
        store=store,
    )
    assert r2["bumped"] == 1
    assert r2["written"] == 0

    node_id = semantic_content_id(project_id, fact)
    node = store.get_node(node_id)
    assert node is not None
    assert node.node_type == NodeType.SEMANTIC

    hits = store.search_fts("LinkedIn golden", project_id, limit=5)
    assert any(
        isinstance(n.data, dict) and "golden" in str(n.data.get("fact", "")).lower()
        for n in hits
    )
