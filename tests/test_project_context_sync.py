"""AGENTS.md hash-gated semantic sync."""

import json
from pathlib import Path

from mcp_server.project_context_sync import sync_project_docs


def test_sync_project_docs_skips_unchanged_hash(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    agents = repo / "AGENTS.md"
    agents.write_text("# Conventions\nUse compact AINL.\n", encoding="utf-8")

    class _Store:
        def __init__(self):
            self.nodes = []

        def write_node(self, node):
            self.nodes.append(node)

    store = _Store()
    pid = "proj_sync_test"
    state = tmp_path / "hashes.json"
    r1 = sync_project_docs(store, pid, repo, state_path=state)
    assert r1["updated"] == 1
    assert len(store.nodes) == 1

    r2 = sync_project_docs(store, pid, repo, state_path=state)
    assert r2["updated"] == 0
    assert len(store.nodes) == 1

    agents.write_text("# Conventions\nUpdated rules.\n", encoding="utf-8")
    r3 = sync_project_docs(store, pid, repo, state_path=state)
    assert r3["updated"] == 1
    assert len(store.nodes) == 2
