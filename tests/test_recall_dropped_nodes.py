"""Recall budget drops low-priority sections first."""

from mcp_server.recall_budget import RecallBudget, format_memory_context_markdown


def _fact(i):
    return {"data": {"fact": f"fact number {i}"}, "confidence": 0.9}


def test_recall_dropped_nodes_when_over_item_limit():
    context = {
        "recent_episodes": [],
        "relevant_facts": [_fact(i) for i in range(20)],
        "applicable_patterns": [],
        "known_failures": [],
        "persona_traits": [],
    }
    budget = RecallBudget(
        max_chars=8000,
        native_max_chars=8000,
        max_episodes=3,
        max_facts=5,
        max_patterns=2,
        max_failures=3,
        max_persona=3,
        detail_level="standard",
        min_prompt_chars_for_recall=60,
    )
    text, stats = format_memory_context_markdown(context, budget, apply_char_cap=False)
    assert stats["recall_dropped_nodes"] == 15
    assert stats["sections"]["facts_used"] == 5
    assert "fact number 0" in text
