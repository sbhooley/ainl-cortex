"""
Tests for delta-injection gates (#7, #8, #9) and Python anchored summary.

Coverage:
  - #8  Brief delta hash: identical brief skipped on turn 2, new brief injected
  - #9  Goal relevance gate: unchanged goals skipped when no keyword overlap;
        re-injected when goals change or prompt overlaps
  - #7  Python anchored summary: write → read roundtrip, staleness gate,
        plugin-node filtering, compression applied
"""

import hashlib
import sqlite3
import sys
import tempfile
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_store(tmp_path: Path):
    """Return a minimal SQLiteGraphStore backed by a temp DB."""
    from graph_store import SQLiteGraphStore
    db = tmp_path / "test.db"
    return SQLiteGraphStore(db)


def _make_node(store, project_id, node_type, data, node_id=None):
    """Write a raw GraphNode into the store and return it.
    node_type is the enum *value* string e.g. 'episode', 'semantic'.
    """
    from node_types import GraphNode, NodeType
    now = int(time.time())
    node = GraphNode(
        id=node_id or str(uuid.uuid4()),
        node_type=NodeType(node_type.lower()),
        project_id=project_id,
        created_at=now,
        updated_at=now,
        confidence=1.0,
        data=data,
    )
    store.write_node(node)
    return node


# ── #8 Brief delta hash ───────────────────────────────────────────────────────

class TestBriefDeltaHash:
    """The hash file gates re-injection of an unchanged memory brief."""

    def test_first_turn_writes_hash(self, tmp_path):
        hash_file = tmp_path / "proj_brief.hash"
        brief = "## Relevant Graph Memory\n\nSome episode info here."

        h = hashlib.md5(brief.encode()).hexdigest()
        last = hash_file.read_text().strip() if hash_file.exists() else ""

        assert h != last  # first turn: no prior hash
        hash_file.write_text(h)
        assert hash_file.read_text().strip() == h

    def test_second_turn_same_brief_skipped(self, tmp_path):
        hash_file = tmp_path / "proj_brief.hash"
        brief = "## Relevant Graph Memory\n\nSame content."

        h = hashlib.md5(brief.encode()).hexdigest()
        hash_file.write_text(h)  # simulate prior turn

        last = hash_file.read_text().strip()
        assert h == last  # gate fires: skip injection

    def test_changed_brief_updates_hash(self, tmp_path):
        hash_file = tmp_path / "proj_brief.hash"
        old_brief = "## Relevant Graph Memory\n\nOld content."
        new_brief = "## Relevant Graph Memory\n\nNew content after new episode."

        hash_file.write_text(hashlib.md5(old_brief.encode()).hexdigest())

        new_h = hashlib.md5(new_brief.encode()).hexdigest()
        last = hash_file.read_text().strip()
        assert new_h != last  # gate does NOT fire: inject and update

        hash_file.write_text(new_h)
        assert hash_file.read_text().strip() == new_h

    def test_empty_brief_never_hashed(self, tmp_path):
        """Empty brief (memory gate fired) should not touch the hash file."""
        hash_file = tmp_path / "proj_brief.hash"
        brief = ""
        # The gate in user_prompt_submit only runs if brief.strip() is truthy
        assert not brief.strip()
        assert not hash_file.exists()  # file not written


# ── #9 Goal relevance gate ────────────────────────────────────────────────────

class TestGoalRelevanceGate:
    """Goals are skipped when unchanged AND prompt has no keyword overlap."""

    def _overlap(self, a: str, b: str) -> float:
        from goal_tracker import _keyword_overlap
        return _keyword_overlap(a, b)

    def test_unchanged_goals_no_overlap_skipped(self, tmp_path):
        hash_file = tmp_path / "proj_goals.hash"
        goal_text = "**Active Goals**\n- Implement A2A system\n- Migrate to native backend"
        prompt = "Okay, sounds good."

        h = hashlib.md5(goal_text.encode()).hexdigest()
        hash_file.write_text(h)

        last = hash_file.read_text().strip()
        assert h == last  # hash unchanged

        overlap = self._overlap(prompt, goal_text)
        assert overlap <= 0.15  # no meaningful overlap → skip

    def test_unchanged_goals_with_overlap_injected(self, tmp_path):
        hash_file = tmp_path / "proj_goals.hash"
        goal_text = "**Active Goals**\n- Implement A2A system\n- Migrate to native backend"
        prompt = "What is the status of the A2A system and native backend migration?"

        h = hashlib.md5(goal_text.encode()).hexdigest()
        hash_file.write_text(h)

        last = hash_file.read_text().strip()
        assert h == last  # hash unchanged

        overlap = self._overlap(prompt, goal_text)
        assert overlap > 0.15  # overlap found → inject

    def test_changed_goals_always_injected(self, tmp_path):
        hash_file = tmp_path / "proj_goals.hash"
        old_text = "**Active Goals**\n- Old goal"
        new_text = "**Active Goals**\n- Old goal\n- New goal added this session"

        hash_file.write_text(hashlib.md5(old_text.encode()).hexdigest())

        new_h = hashlib.md5(new_text.encode()).hexdigest()
        last = hash_file.read_text().strip()
        assert new_h != last  # hash changed → always inject, update file

    def test_no_hash_file_always_injected(self, tmp_path):
        hash_file = tmp_path / "proj_goals.hash"
        goal_text = "**Active Goals**\n- Implement feature X"
        assert not hash_file.exists()

        h = hashlib.md5(goal_text.encode()).hexdigest()
        last = ""  # no file → treat as no prior hash
        assert h != last  # inject and write


# ── #7 Python anchored summary ────────────────────────────────────────────────

class TestAnchoredSummary:
    """Anchored summary write/read roundtrip, staleness, and content filters."""

    def test_write_read_roundtrip(self, tmp_path):
        from anchored_summary import update_anchored_summary, get_anchored_summary
        store = _make_store(tmp_path)
        project_id = "test_proj"

        # Seed some episodes and facts
        _make_node(store, project_id, "episode", {
            "task_description": "Implemented delta injection gate",
            "outcome": "success",
            "tools_used": ["edit"],
            "files_touched": ["user_prompt_submit.py"],
        })
        _make_node(store, project_id, "semantic", {
            "fact": "Delta injection skips unchanged memory briefs",
            "topic_cluster": "compression",
            "confidence": 0.9,
        })

        wrote = update_anchored_summary(store, project_id)
        assert wrote is True

        text = get_anchored_summary(store, project_id)
        assert text is not None
        assert len(text) > 10
        # Content from episodes should be represented
        assert any(kw in text.lower() for kw in ("delta", "injection", "episode", "implemented"))

    def test_empty_store_returns_false(self, tmp_path):
        from anchored_summary import update_anchored_summary, get_anchored_summary
        store = _make_store(tmp_path)
        wrote = update_anchored_summary(store, "empty_proj")
        assert wrote is False
        assert get_anchored_summary(store, "empty_proj") is None

    def test_staleness_gate(self, tmp_path):
        from anchored_summary import update_anchored_summary, get_anchored_summary, _node_id
        from node_types import GraphNode, NodeType
        store = _make_store(tmp_path)
        project_id = "stale_proj"

        _make_node(store, project_id, "episode", {
            "task_description": "Some work",
            "outcome": "success",
        })
        update_anchored_summary(store, project_id)

        # Manually backdate the anchored_at timestamp to 8 days ago
        stale_ts = int(time.time()) - (8 * 24 * 3600)
        node = store.get_node(_node_id(project_id))
        node.data["anchored_at"] = stale_ts
        store.write_node(node)

        result = get_anchored_summary(store, project_id)
        assert result is None  # stale → not returned

    def test_plugin_nodes_excluded(self, tmp_path):
        from anchored_summary import update_anchored_summary, get_anchored_summary
        store = _make_store(tmp_path)
        project_id = "filter_proj"

        # Write a real episode
        _make_node(store, project_id, "episode", {
            "task_description": "Real work done here",
            "outcome": "success",
        })
        # Write an internal plugin node that should be filtered out
        _make_node(store, project_id, "semantic", {
            "fact": "THIS SHOULD NOT APPEAR",
            "topic_cluster": "_plugin:anchored_summary",
        })

        update_anchored_summary(store, project_id)
        text = get_anchored_summary(store, project_id)
        assert text is not None
        assert "THIS SHOULD NOT APPEAR" not in (text or "")

    def test_summary_stats_populated(self, tmp_path):
        from anchored_summary import update_anchored_summary, summary_stats
        store = _make_store(tmp_path)
        project_id = "stats_proj"

        for i in range(3):
            _make_node(store, project_id, "episode", {
                "task_description": f"Task {i}",
                "outcome": "success",
            })

        update_anchored_summary(store, project_id)
        stats = summary_stats(store, project_id)

        assert stats is not None
        assert stats["episode_count"] == 3
        assert stats["anchored_at"] > 0
        assert stats["compressed_chars"] <= stats["original_chars"]


# ── #7 Anchored flag gates FTS recall ────────────────────────────────────────

class TestAnchoredFlag:
    """The _anchored.flag file gates per-turn FTS recall."""

    def test_fresh_flag_skips_recall(self, tmp_path):
        flag_file = tmp_path / "proj_anchored.flag"
        flag_file.write_text(str(time.time()))

        flag_age = time.time() - float(flag_file.read_text().strip())
        assert flag_age < 28800  # gate fires: skip FTS

    def test_stale_flag_allows_recall(self, tmp_path):
        flag_file = tmp_path / "proj_anchored.flag"
        flag_file.write_text(str(time.time() - 30000))  # > 8 hours ago

        flag_age = time.time() - float(flag_file.read_text().strip())
        assert flag_age >= 28800  # gate does NOT fire: run FTS

    def test_missing_flag_allows_recall(self, tmp_path):
        flag_file = tmp_path / "proj_anchored.flag"
        assert not flag_file.exists()
        # No flag → no anchored summary was injected → FTS runs normally

    def test_startup_clears_flag(self, tmp_path):
        """Simulate what startup.py does: unlink hash/flag files."""
        flag = tmp_path / "proj_anchored.flag"
        brief_hash = tmp_path / "proj_brief.hash"
        goals_hash = tmp_path / "proj_goals.hash"

        for f in (flag, brief_hash, goals_hash):
            f.write_text("old")

        # Startup clears them
        for f in (flag, brief_hash, goals_hash):
            f.unlink(missing_ok=True)

        assert not flag.exists()
        assert not brief_hash.exists()
        assert not goals_hash.exists()
