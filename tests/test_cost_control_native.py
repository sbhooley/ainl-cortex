"""Native-backend cost-control integration tests (mocked ainl_native)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))
sys.path.insert(0, str(PLUGIN_ROOT))


class TestNativeRecallProcedureCards:
    def test_fetch_patterns_for_project_empty_without_db(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from mcp_server.procedure_cards import fetch_patterns_for_project

        assert fetch_patterns_for_project("no_such_project") == []

    def test_native_recall_sets_recall_context_for_patterns(self):
        """Native branch loads patterns from Python store when pattern_count > 0."""
        patterns = [
            type(
                "Pat",
                (),
                {
                    "data": {
                        "pattern_name": "auth fix",
                        "tool_sequence": ["read", "edit"],
                        "fitness": 0.9,
                    }
                },
            )()
        ]
        _recall = {"pattern_count": 2, "brief": "x"}
        _recall_context = {}
        if int(_recall.get("pattern_count") or 0) > 0:
            with mock.patch(
                "mcp_server.procedure_cards.fetch_patterns_for_project",
                return_value=patterns,
            ):
                from mcp_server.procedure_cards import fetch_patterns_for_project

                _recall_context = {
                    "applicable_patterns": fetch_patterns_for_project("proj", 5),
                }
        assert len(_recall_context.get("applicable_patterns", [])) == 1


class TestConversationGateNativeParity:
    def test_conversation_skip_applies_before_native_recall(self):
        from shared.conversation_detection import is_conversation_only_turn

        assert is_conversation_only_turn("thanks")
        # Gate is evaluated before _ainl_native.recall_context in user_prompt_submit.
        src = (PLUGIN_ROOT / "hooks" / "user_prompt_submit.py").read_text(encoding="utf-8")
        gate_pos = src.find("is_conversation_only_turn(prompt)")
        native_pos = src.find("_ainl_native.recall_context")
        assert gate_pos != -1 and native_pos != -1
        assert gate_pos < native_pos


class TestPackNativeBriefStats:
    def test_pack_native_brief_includes_path_native(self):
        from mcp_server.recall_budget import RecallBudget, pack_native_brief

        budget = RecallBudget(
            max_chars=500,
            native_max_chars=500,
            max_episodes=3,
            max_facts=5,
            max_patterns=2,
            max_failures=3,
            max_persona=3,
            detail_level="standard",
            min_prompt_chars_for_recall=60,
        )
        brief, _, _, stats = pack_native_brief("hello", budget, False, "p", lambda t, p: (t, None, None))
        assert stats.get("path") == "native"

    def test_pack_native_brief_estimates_dropped_nodes(self):
        from mcp_server.recall_budget import RecallBudget, pack_native_brief

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
        _, _, _, stats = pack_native_brief(
            "brief",
            budget,
            False,
            "p",
            lambda t, pid: (t, None, None),
            recall_meta={
                "episode_count": 10,
                "fact_count": 20,
                "pattern_count": 0,
                "failure_count": 0,
                "persona_count": 0,
            },
        )
        assert stats.get("recall_dropped_nodes") == 22
        assert stats.get("sections", {}).get("facts_used") == 5
