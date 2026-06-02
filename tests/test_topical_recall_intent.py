"""Recall intent and topical knowledge block."""

from __future__ import annotations

from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
HOOKS = PLUGIN_ROOT / "hooks"


@pytest.fixture(autouse=True)
def _path():
    import sys

    for p in (str(PLUGIN_ROOT / "mcp_server"), str(HOOKS)):
        if p not in sys.path:
            sys.path.insert(0, p)


def test_topical_memory_recall_intent():
    from shared.conversation_detection import (
        implies_memory_recall_intent,
        implies_topical_memory_recall_intent,
    )

    q = "What about your research on clipping and the game plan?"
    lower = q.lower()
    assert implies_topical_memory_recall_intent(lower)
    assert implies_memory_recall_intent(lower)


def test_format_topical_knowledge_block(tmp_path, monkeypatch):
    from graph_store import get_graph_store
    from knowledge_writer import ingest_facts
    from topical_recall import format_topical_knowledge_block

    project_id = "topicalrecall1234"
    db = tmp_path / "ainl_memory.db"
    monkeypatch.setattr("knowledge_writer.graph_db_path", lambda pid: db)

    store = get_graph_store(db)
    ingest_facts(
        project_id,
        ["LinkedIn golden 60-minute window: comments in the first hour matter."],
        source_kind="research",
        tags=["research", "clipping"],
        store=store,
    )
    monkeypatch.setattr("topical_recall.open_store", lambda pid: store)

    block = format_topical_knowledge_block(
        project_id, "What did your research say about LinkedIn clipping?"
    )
    assert block is not None
    assert "Relevant knowledge" in block
    assert "golden" in block.lower() or "linkedin" in block.lower()
