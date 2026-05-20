"""Procedure card matching for recall injection."""

from mcp_server.procedure_cards import format_procedure_cards_section, match_procedure_cards


def test_match_procedure_cards_overlap():
    patterns = [
        {"data": {"pattern_name": "auth fix", "tool_sequence": ["read", "edit", "bash"], "fitness": 0.8}},
    ]
    matches = match_procedure_cards("fix auth.py test failure", patterns)
    assert len(matches) >= 1
    section = format_procedure_cards_section(matches)
    assert "Procedure cards" in section
    assert "auth fix" in section
