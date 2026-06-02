"""Artifact ingestion from session captures."""

from __future__ import annotations

from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _path():
    import sys

    for p in (str(PLUGIN_ROOT / "mcp_server"), str(PLUGIN_ROOT / "hooks")):
        if p not in sys.path:
            sys.path.insert(0, p)


def test_artifact_ingest_from_fixture(tmp_path, monkeypatch):
    from artifact_ingest import run
    from graph_store import get_graph_store
    from knowledge_writer import graph_db_path

    fixture = Path(__file__).parent / "fixtures" / "craigcast_research_snippet.md"
    import uuid

    project_id = "art" + uuid.uuid4().hex[:12]

    db = tmp_path / "graph_memory" / "ainl_memory.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    store_holder = {"store": None}

    def _open_store(pid):
        if store_holder["store"] is None:
            store_holder["store"] = get_graph_store(db)
        return store_holder["store"]

    monkeypatch.setattr("knowledge_writer.graph_db_path", lambda pid: db)
    monkeypatch.setattr("knowledge_writer.open_store", _open_store)
    monkeypatch.setattr("artifact_ingest.open_store", _open_store)

    session_data = {
        "tool_captures": [
            {
                "tool": "write",
                "file": str(fixture),
                "ingest_candidate": True,
                "success": True,
            }
        ],
        "tools_used": ["write"],
        "files_touched": [str(fixture)],
    }

    result = run(project_id, session_data)
    assert (result.get("written", 0) + result.get("bumped", 0)) >= 1

    from node_types import NodeType

    store = store_holder["store"] or get_graph_store(db)
    semantics = store.query_by_type(NodeType.SEMANTIC, project_id, limit=30)
    facts = [
        str(n.data.get("fact", ""))
        for n in semantics
        if isinstance(n.data, dict)
    ]
    assert len(facts) >= 3
    assert any("golden" in f.lower() or "linkedin" in f.lower() for f in facts)
