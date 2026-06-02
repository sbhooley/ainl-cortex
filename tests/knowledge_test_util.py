"""Shared helpers for knowledge-capture tests (isolated SQLite per project)."""

from __future__ import annotations

from pathlib import Path

import pytest


def bind_test_graph_store(monkeypatch, project_id: str, db_path: Path):
    """
    Pin all knowledge modules to one in-memory SQLite file.

    ``monkeypatch.setattr("knowledge_writer.graph_db_path")`` alone is not enough
    when submodules did ``from knowledge_writer import open_store`` at import time.
    """
    from graph_store import get_graph_store

    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = get_graph_store(db_path)

    def _open_store(pid: str):
        if pid != project_id:
            pytest.fail(f"unexpected project_id {pid!r}, expected {project_id!r}")
        return store

    def _db_path(pid: str) -> Path:
        if pid != project_id:
            pytest.fail(f"unexpected project_id {pid!r}, expected {project_id!r}")
        return db_path

    for mod in (
        "knowledge_writer",
        "prompt_remember_ingest",
        "artifact_ingest",
        "research_capture",
        "session_synthesis",
        "claude_memory_bridge",
    ):
        monkeypatch.setattr(f"{mod}.open_store", _open_store, raising=False)
        monkeypatch.setattr(f"{mod}.graph_db_path", _db_path, raising=False)

    return store
