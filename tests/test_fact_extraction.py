"""Tests for heuristic fact extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _path():
    import sys

    mcp = str(PLUGIN_ROOT / "mcp_server")
    if mcp not in sys.path:
        sys.path.insert(0, mcp)


def test_heuristic_extracts_linkedin_golden_window():
    from fact_extraction import extract_facts_heuristic

    text = Path(__file__).parent.joinpath(
        "fixtures", "craigcast_research_snippet.md"
    ).read_text(encoding="utf-8")
    facts = extract_facts_heuristic(text, max_facts=20, context_title="algo")
    joined = " ".join(facts).lower()
    assert "linkedin" in joined or "golden" in joined or "60" in joined
    assert len(facts) >= 3


def test_semantic_content_id_stable():
    from node_types import semantic_content_id

    a = semantic_content_id("proj1", "LinkedIn golden 60-minute window")
    b = semantic_content_id("proj1", "LinkedIn  golden   60-minute window")
    assert a == b
