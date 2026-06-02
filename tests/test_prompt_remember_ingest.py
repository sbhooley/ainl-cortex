"""Prompt remember auto-ingest."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _path():
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


@pytest.fixture
def plugin_inbox(tmp_path, monkeypatch):
    root = tmp_path / "plugin"
    (root / "inbox").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    return root


def test_prompt_remember_ingest_writes_facts(plugin_inbox, monkeypatch, tmp_path):
    from prompt_remember_ingest import run

    project_id = "proj_remember_test"
    db = tmp_path / "ainl_memory.db"
    _bind_store(monkeypatch, project_id, db)

    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Game plan: batch 20 Craigcast clips per week using "
                                "capcut templates and LinkedIn native upload."
                            ),
                        }
                    ],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    out = run(
        project_id,
        "remember this",
        transcript_path=str(transcript),
        plugin_root=plugin_inbox,
        session_id="sess-1",
    )
    assert out.get("written", 0) >= 1
    assert "assistant_transcript" in (out.get("sources") or [])
