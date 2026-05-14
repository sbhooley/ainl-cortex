"""Golden-style tests for recall budget packing and repartition integrity helper."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN / "mcp_server"))

from recall_budget import (  # noqa: E402
    RecallBudget,
    apply_char_ceiling,
    format_memory_context_markdown,
    memory_brief_has_content,
    recall_budget_from_memory_config,
)


def test_recall_budget_defaults():
    b = recall_budget_from_memory_config({"max_context_tokens": 100})
    assert b.max_chars == 400


def test_apply_char_ceiling():
    s, t = apply_char_ceiling("hello world", 20)
    assert t is False
    s2, t2 = apply_char_ceiling("x" * 200, 50)
    assert t2 is True
    assert len(s2) <= 50


def test_format_memory_tiered_and_budget():
    ctx = {
        "recent_episodes": [
            {
                "id": "e1",
                "created_at": 1700000000,
                "data": {"task_description": "task a", "outcome": "success"},
            }
        ],
        "relevant_facts": [
            {"data": {"fact": "alpha"}, "confidence": 0.9},
            {"data": {"fact": "beta"}, "confidence": 0.8},
        ],
        "applicable_patterns": [],
        "known_failures": [
            {
                "data": {"file": "x.py", "line": 1, "error_message": "boom"},
            }
        ],
        "persona_traits": [],
    }
    budget = RecallBudget(
        max_chars=400,
        native_max_chars=400,
        max_episodes=3,
        max_facts=2,
        max_patterns=2,
        max_failures=3,
        max_persona=3,
        detail_level="standard",
        min_prompt_chars_for_recall=10,
    )
    text, stats = format_memory_context_markdown(ctx, budget)
    assert "## Memory (summary)" in text
    assert "alpha" in text
    assert stats["recall_truncated"] is False
    assert memory_brief_has_content(text)


def test_compile_memory_context_empty_db(tmp_path):
    schema = (PLUGIN / "mcp_server" / "schema.sql").read_text()
    db = tmp_path / "ainl_memory.db"
    con = sqlite3.connect(str(db))
    con.executescript(schema)
    con.close()
    from graph_store import get_graph_store  # noqa: E402
    from retrieval import MemoryRetrieval, RetrievalContext  # noqa: E402

    store = get_graph_store(db)
    mr = MemoryRetrieval(store)
    ctx = RetrievalContext(project_id="abc123456789abcde", current_task="hello")
    out = mr.compile_memory_context(ctx, max_nodes=5)
    for k in (
        "recent_episodes",
        "relevant_facts",
        "applicable_patterns",
        "known_failures",
        "persona_traits",
    ):
        assert k in out
        assert isinstance(out[k], list)


def test_verify_repartition_integrity_script(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE ainl_graph_nodes (id TEXT PRIMARY KEY);
        CREATE TABLE ainl_graph_edges (
          id TEXT PRIMARY KEY,
          from_node TEXT NOT NULL,
          to_node TEXT NOT NULL
        );
        INSERT INTO ainl_graph_nodes VALUES ('a'), ('b');
        INSERT INTO ainl_graph_edges VALUES ('e1', 'a', 'b');
        """
    )
    conn.close()
    script = PLUGIN / "scripts" / "verify_repartition_integrity.py"
    r = subprocess.run(
        [sys.executable, str(script), str(db)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0

    conn = sqlite3.connect(str(db))
    conn.execute("INSERT INTO ainl_graph_edges VALUES ('bad', 'a', 'missing')")
    conn.commit()
    conn.close()
    r2 = subprocess.run(
        [sys.executable, str(script), str(db)],
        capture_output=True,
        text=True,
    )
    assert r2.returncode == 1
