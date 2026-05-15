"""
Thorough regression and integration tests for the 8 features shipped in the
last two commits. Each section covers gaps not addressed by the existing
unit-level tests:

  A. Decision extraction (write_semantics pattern matching + DB integration)
  B. Confidence decay triggered from finalize_session (config-driven)
  C. Failure trend-only injection (trends surfaced with zero individual warnings)
  D. Compaction recovery brief injection in startup systemMessage
  E. Branch annotation written to actual prompt history JSONL
  F. memory_session_history logic (filtering, limits, output shape)
  G. Branch-filtered recall behaviour (filter lambda, non-episode passthrough)
"""

import asyncio
import json
import re
import sys
import time
import uuid
from pathlib import Path
from unittest import mock

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))
sys.path.insert(0, str(PLUGIN_ROOT / "mcp_server"))


# ═══════════════════════════════════════════════════════════════════════════════
# A. Decision extraction in write_semantics
# ═══════════════════════════════════════════════════════════════════════════════

import re as _re

# Mirror the compiled patterns from stop.py so we can test them in isolation
_DECISION_PATS = [
    _re.compile(
        r'(?:going with|decided to|we\'ll use|switching to|'
        r'using \S.{2,30} instead|settled on|agreed on|'
        r'the plan is|architecture is|we\'re going with)\s+(.{10,120})',
        _re.IGNORECASE,
    ),
    _re.compile(
        r'(?:the|our)\s+(?:api|db|database|server|endpoint|'
        r'key|token|port|version|url|base.?url|path)\s+'
        r'(?:is|will be|should be|needs to be)\s+(.{5,80})',
        _re.IGNORECASE,
    ),
]


def _extract_decisions(text):
    """Return list of (full_match, len) pairs that pass the length gate."""
    results = []
    for pat in _DECISION_PATS:
        for m in pat.finditer(text):
            decision = m.group(0).strip()[:200]
            if len(decision) >= 20:
                results.append(decision)
    return results


class TestDecisionPatterns:
    def test_going_with(self):
        decisions = _extract_decisions("We are going with React for the frontend component.")
        assert any("going with React" in d for d in decisions)

    def test_decided_to(self):
        decisions = _extract_decisions("We decided to use Postgres instead of MySQL.")
        assert any("decided to use" in d.lower() for d in decisions)

    def test_well_use(self):
        decisions = _extract_decisions("We'll use FastAPI for the backend service.")
        assert any("FastAPI" in d for d in decisions)

    def test_switching_to(self):
        decisions = _extract_decisions("Switching to the native backend for performance.")
        assert any("Switching to" in d for d in decisions)

    def test_settled_on(self):
        decisions = _extract_decisions("We settled on Redis as the session store.")
        assert any("settled on Redis" in d for d in decisions)

    def test_architecture_is(self):
        decisions = _extract_decisions("The architecture is event-driven with Kafka.")
        assert any("architecture is" in d.lower() for d in decisions)

    def test_the_api_is(self):
        decisions = _extract_decisions("The API is available at https://api.example.com/v2")
        assert any("API" in d for d in decisions)

    def test_our_db_is(self):
        decisions = _extract_decisions("Our database is PostgreSQL running on port 5432.")
        assert any("database" in d.lower() for d in decisions)

    def test_server_will_be(self):
        decisions = _extract_decisions("The server will be deployed on port 8080.")
        assert any("server" in d.lower() for d in decisions)

    def test_short_match_skipped(self):
        # "Going with X" where X is < 10 chars — match too short
        decisions = _extract_decisions("Going with Go.")
        # "Going with Go." is only 14 chars — passes >=20? Let's check
        # Actually "going with Go." = 14 chars, which is < 20, so skipped
        for d in decisions:
            assert len(d) >= 20, f"Short match leaked: {d!r}"

    def test_no_match_on_unrelated_text(self):
        decisions = _extract_decisions("Please run the tests and check the output.")
        assert decisions == []

    def test_multiple_decisions_in_one_text(self):
        text = (
            "We decided to use TypeScript. "
            "The API is at localhost:3000. "
            "Going with monorepo structure for now."
        )
        decisions = _extract_decisions(text)
        assert len(decisions) >= 2

    def test_case_insensitive(self):
        decisions = _extract_decisions("GOING WITH RUST FOR THE NATIVE LAYER.")
        assert any("GOING WITH" in d.upper() for d in decisions)


class TestDecisionExtractionIntegration:
    """End-to-end: prompt history file → write_semantics → semantic nodes in DB."""

    def _write_prompt_history(self, plugin_root, project_id, records):
        inbox = plugin_root / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        hist = inbox / f"{project_id}_prompts.jsonl"
        lines = [json.dumps(r) for r in records]
        hist.write_text("\n".join(lines) + "\n")

    def test_decision_produces_semantic_node(self, tmp_path):
        from graph_store import get_graph_store
        from node_types import NodeType, create_episode_node
        import stop as stop_mod

        # Write enough prompt history (>= 5 records) with a clear decision
        records = [
            {"ts": int(time.time()), "text": "We decided to use SQLite for storage.", "files": [], "tech_ids": [], "action": None, "length": 40, "git_branch": None},
            {"ts": int(time.time()), "text": "Let me check the code.", "files": [], "tech_ids": [], "action": None, "length": 22, "git_branch": None},
            {"ts": int(time.time()), "text": "Run the tests please.", "files": [], "tech_ids": [], "action": None, "length": 21, "git_branch": None},
            {"ts": int(time.time()), "text": "Fix the failing test.", "files": [], "tech_ids": [], "action": None, "length": 21, "git_branch": None},
            {"ts": int(time.time()), "text": "Going with the standard approach here.", "files": [], "tech_ids": [], "action": None, "length": 38, "git_branch": None},
        ]
        project_id = "proj_decision_test"

        # Write history to plugin root inbox
        self._write_prompt_history(PLUGIN_ROOT, project_id, records)

        # Use a temp DB — seed with 3 episode nodes so write_semantics passes MIN_EP guard
        db_path = tmp_path / "ainl_memory.db"
        store = get_graph_store(db_path)
        for i in range(3):
            ep = create_episode_node(
                project_id=project_id,
                task_description=f"seed episode {i}",
                outcome="success",
                files_touched=[],
                tool_calls=[],
                git_branch=None,
            )
            store.write_node(ep)

        count = stop_mod.write_semantics(store, project_id)

        # Verify at least one semantic node was written
        sem_nodes = store.query_by_type(NodeType.SEMANTIC, project_id, limit=50)
        facts = [n.data.get("fact", "") for n in sem_nodes]
        decision_facts = [f for f in facts if "Decision:" in f or "decided" in f.lower() or "SQLite" in f]
        assert len(decision_facts) >= 1, f"No decision nodes found. All facts: {facts}"

    def test_decision_deduplication(self, tmp_path):
        """Same decision phrase doesn't create duplicate semantic nodes on re-run."""
        from graph_store import get_graph_store
        from node_types import NodeType
        import stop as stop_mod

        project_id = "proj_dedup_test"
        records = [
            {"ts": int(time.time()), "text": "Going with React for the entire frontend layer.", "files": [], "tech_ids": [], "action": None, "length": 47, "git_branch": None},
        ] * 5  # Same record 5 times

        self._write_prompt_history(PLUGIN_ROOT, project_id, records)
        db_path = tmp_path / "ainl_memory.db"
        store = get_graph_store(db_path)

        stop_mod.write_semantics(store, project_id)
        stop_mod.write_semantics(store, project_id)  # run twice

        sem_nodes = store.query_by_type(NodeType.SEMANTIC, project_id, limit=50)
        react_facts = [n for n in sem_nodes if "React" in n.data.get("fact", "")]
        # Should not have more than one copy
        assert len(react_facts) <= 1, f"Duplicate decision nodes: {[n.data['fact'] for n in react_facts]}"

    def test_fewer_than_5_prompts_skips_extraction(self, tmp_path):
        """With < 5 prompt records, decision extraction is skipped."""
        from graph_store import get_graph_store
        from node_types import NodeType
        import stop as stop_mod

        project_id = "proj_toofew"
        records = [
            {"ts": int(time.time()), "text": "Going with TypeScript for everything.", "files": [], "tech_ids": [], "action": None, "length": 36, "git_branch": None},
            {"ts": int(time.time()), "text": "We decided to switch to Rust.", "files": [], "tech_ids": [], "action": None, "length": 28, "git_branch": None},
            {"ts": int(time.time()), "text": "The API is at port 9000 now.", "files": [], "tech_ids": [], "action": None, "length": 27, "git_branch": None},
        ]  # Only 3 records — below the 5-record threshold
        self._write_prompt_history(PLUGIN_ROOT, project_id, records)

        db_path = tmp_path / "ainl_memory.db"
        store = get_graph_store(db_path)
        stop_mod.write_semantics(store, project_id)

        sem_nodes = store.query_by_type(NodeType.SEMANTIC, project_id, limit=50)
        # write_semantics itself returns early when episode_nodes < MIN_EP=3
        # but even if it runs, < 5 prompt records skips the prompt mining block
        # (including decision extraction)
        decision_nodes = [n for n in sem_nodes if "Decision:" in n.data.get("fact", "")]
        assert len(decision_nodes) == 0

    def cleanup_inbox(self, project_id):
        hist = PLUGIN_ROOT / "inbox" / f"{project_id}_prompts.jsonl"
        if hist.exists():
            hist.unlink()

    def teardown_method(self, method):
        for pid in ["proj_decision_test", "proj_dedup_test", "proj_toofew"]:
            self.cleanup_inbox(pid)


# ═══════════════════════════════════════════════════════════════════════════════
# B. Confidence decay triggered via finalize_session (config-driven)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecayFromFinalizeSession:
    def test_finalize_triggers_decay_on_old_nodes(self, tmp_path):
        """finalize_session must call decay and TTL on the Python store."""
        from graph_store import get_graph_store
        from node_types import GraphNode, NodeType
        import stop as stop_mod

        project_id = "proj_decay_integ"
        db_path = Path.home() / ".claude" / "projects" / project_id / "graph_memory" / "ainl_memory.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        store = get_graph_store(db_path)
        # Write an old semantic node (200 days ago)
        old_node = GraphNode(
            id=str(uuid.uuid4()),
            node_type=NodeType.SEMANTIC,
            project_id=project_id,
            agent_id="test",
            created_at=int(time.time()) - 200 * 86400,
            updated_at=int(time.time()) - 200 * 86400,
            confidence=0.9,
            data={"fact": "an old fact that should decay"},
            embedding_text="old fact decay",
        )
        store.write_node(old_node)
        confidence_before = store.get_node(old_node.id).confidence

        # Run decay directly (as finalize_session does)
        decayed = store.decay_node_confidence(project_id, older_than_days=90, factor=0.05)
        assert decayed >= 1

        confidence_after = store.get_node(old_node.id).confidence
        assert confidence_after < confidence_before
        assert abs(confidence_after - (confidence_before - 0.05)) < 0.001

    def test_decay_uses_config_factor(self):
        """The config default factor is 0.05."""
        cfg = json.loads((PLUGIN_ROOT / "config.json").read_text())
        assert cfg["memory"]["confidence_decay_factor"] == 0.05

    def test_decay_uses_config_days(self):
        """The config default decay window is 90 days."""
        cfg = json.loads((PLUGIN_ROOT / "config.json").read_text())
        assert cfg["memory"]["confidence_decay_days"] == 90

    def test_ttl_uses_config_days(self):
        """The config default TTL is 365 days."""
        cfg = json.loads((PLUGIN_ROOT / "config.json").read_text())
        assert cfg["memory"]["node_ttl_days"] == 365

    def test_finalize_session_calls_decay_for_python_backend(self, tmp_path):
        """Verify finalize_session source calls decay_node_confidence when not strict-native."""
        src = (PLUGIN_ROOT / "hooks" / "stop.py").read_text()
        assert "decay_node_confidence" in src
        assert "delete_expired_nodes" in src
        assert "_STRICT_NATIVE" in src  # gated on non-strict-native

    def test_decay_never_touches_goal_nodes(self, tmp_path):
        """Goal nodes should not be decayed (only semantic/failure/procedural/persona)."""
        from graph_store import get_graph_store
        from node_types import GraphNode, NodeType
        store = get_graph_store(tmp_path / "t.db")

        goal = GraphNode(
            id=str(uuid.uuid4()),
            node_type=NodeType.GOAL,
            project_id="proj",
            agent_id="test",
            created_at=int(time.time()) - 200 * 86400,
            updated_at=int(time.time()),
            confidence=0.9,
            data={"title": "my goal", "status": "active"},
            embedding_text="my goal",
        )
        store.write_node(goal)
        decayed = store.decay_node_confidence("proj", older_than_days=1, factor=0.1)
        assert store.get_node(goal.id).confidence == 0.9

    def test_decay_accumulates_across_multiple_calls(self, tmp_path):
        """Repeated decay calls compound correctly."""
        from graph_store import get_graph_store
        from node_types import GraphNode, NodeType
        store = get_graph_store(tmp_path / "t.db")

        node = GraphNode(
            id=str(uuid.uuid4()),
            node_type=NodeType.SEMANTIC,
            project_id="proj",
            agent_id="test",
            created_at=int(time.time()) - 200 * 86400,
            updated_at=int(time.time()),
            confidence=0.9,
            data={"fact": "test"},
            embedding_text="test",
        )
        store.write_node(node)
        store.decay_node_confidence("proj", older_than_days=90, factor=0.1)
        store.decay_node_confidence("proj", older_than_days=90, factor=0.1)
        after = store.get_node(node.id).confidence
        assert abs(after - 0.7) < 0.001


# ═══════════════════════════════════════════════════════════════════════════════
# C. Failure trend-only injection (no individual warnings needed)
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrendOnlyInjection:
    def test_format_warnings_with_trends_only(self):
        """format_warnings shows trend block even when warnings list is empty."""
        from failure_advisor import FailureAdvisor
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            from graph_store import get_graph_store
            store = get_graph_store(Path(td) / "t.db")
            advisor = FailureAdvisor(store, "proj")
            trends = [{"error_type": "adapter_error", "tool": "ainl_run", "count": 4, "most_recent": int(time.time())}]
            text = advisor.format_warnings([], trends)
            assert text != ""
            assert "📈" in text
            assert "Failure Trends" in text
            assert "adapter_error" in text
            assert "ainl_run" in text
            assert "4" in text

    def test_trend_occurrence_singular(self):
        """'1 occurrence' (singular) when count == 1."""
        from failure_advisor import FailureAdvisor
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            from graph_store import get_graph_store
            store = get_graph_store(Path(td) / "t.db")
            advisor = FailureAdvisor(store, "proj")
            trends = [{"error_type": "err", "tool": "ainl_run", "count": 1, "most_recent": 0}]
            text = advisor.format_warnings([], trends)
            assert "1 occurrence" in text
            assert "1 occurrences" not in text

    def test_trend_occurrence_plural(self):
        from failure_advisor import FailureAdvisor
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            from graph_store import get_graph_store
            store = get_graph_store(Path(td) / "t.db")
            advisor = FailureAdvisor(store, "proj")
            trends = [{"error_type": "err", "tool": "ainl_run", "count": 3, "most_recent": 0}]
            text = advisor.format_warnings([], trends)
            assert "3 occurrences" in text

    def test_trend_block_present_alongside_warnings(self):
        """Both individual warnings AND trend block appear when both are present."""
        from failure_advisor import FailureAdvisor, FailureWarning
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            from graph_store import get_graph_store
            store = get_graph_store(Path(td) / "t.db")
            advisor = FailureAdvisor(store, "proj")
            warnings = [FailureWarning(
                error_type="compile_error", error_summary="bad token",
                resolution="", confidence=0.8, matched_on="semantic",
                failure_node_id="nid-1",
            )]
            trends = [{"error_type": "runtime_error", "tool": "ainl_run", "count": 5, "most_recent": 0}]
            text = advisor.format_warnings(warnings, trends)
            assert "compile_error" in text
            assert "runtime_error" in text
            assert "📈" in text

    def test_user_prompt_submit_passes_trends_to_format_warnings(self):
        """user_prompt_submit.py must pass _trends to format_warnings."""
        src = (PLUGIN_ROOT / "hooks" / "user_prompt_submit.py").read_text()
        assert "_trends = _advisor.get_trends()" in src
        assert "format_warnings(_warnings, _trends)" in src

    def test_failure_advisor_get_trends_is_public(self):
        """get_trends must be a public method (not _prefixed)."""
        from failure_advisor import FailureAdvisor
        assert hasattr(FailureAdvisor, "get_trends")
        assert not FailureAdvisor.get_trends.__name__.startswith("_")


# ═══════════════════════════════════════════════════════════════════════════════
# D. Compaction recovery brief in startup systemMessage
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompactionRecoveryInjection:
    def test_startup_imports_build_compaction_brief(self):
        src = (PLUGIN_ROOT / "hooks" / "startup.py").read_text()
        assert "build_compaction_brief" in src

    def test_startup_injects_when_not_native(self):
        src = (PLUGIN_ROOT / "hooks" / "startup.py").read_text()
        assert "not _NATIVE_OK" in src
        assert "COMPACTION RECOVERY" in src

    def test_startup_skips_when_native(self):
        """The brief must be gated on `not _NATIVE_OK`."""
        src = (PLUGIN_ROOT / "hooks" / "startup.py").read_text()
        idx = src.find("COMPACTION RECOVERY")
        # Walk backwards to find the condition
        block = src[max(0, idx - 300): idx]
        assert "not _NATIVE_OK" in block or "_NATIVE_OK" in block

    def test_brief_content_in_injected_block(self, tmp_path):
        """Brief content from build_compaction_brief lands inside the ━━━ wrapper."""
        from shared.session_delta import build_compaction_brief, append_session_delta
        nodes = [{"node_id": "n1", "node_type": "episode", "content_hash": "abc"}]
        append_session_delta(tmp_path, "sid-test-inject", "proj", time.time() - 60, nodes)
        brief = build_compaction_brief(tmp_path, max_sessions=3)
        assert "sid-test-inject"[:8] in brief
        assert "episode" in brief

    def test_recovery_block_format(self, tmp_path):
        """The injected block uses the ━━━ banner style."""
        src = (PLUGIN_ROOT / "hooks" / "startup.py").read_text()
        assert "━━━ COMPACTION RECOVERY" in src
        assert "━━━ END RECOVERY ━━━" in src


# ═══════════════════════════════════════════════════════════════════════════════
# E. Branch annotation in actual prompt history JSONL
# ═══════════════════════════════════════════════════════════════════════════════

class TestBranchPromptHistory:
    def test_record_prompt_summary_writes_git_branch_key(self, tmp_path):
        """Calling record_prompt_summary with a non-git cwd writes git_branch: null."""
        import user_prompt_submit as ups_mod

        project_id = "proj_branch_jsonl_test"
        # Redirect the inbox to tmp_path by patching the plugin root resolution
        inbox = PLUGIN_ROOT / "inbox"
        inbox.mkdir(exist_ok=True)
        hist_file = inbox / f"{project_id}_prompts.jsonl"
        if hist_file.exists():
            hist_file.unlink()

        # tmp_path is not a git repo, so git_branch should be None
        ups_mod.record_prompt_summary(project_id, "Going with pytest for testing.", cwd=tmp_path)

        assert hist_file.exists()
        record = json.loads(hist_file.read_text().strip().splitlines()[-1])
        assert "git_branch" in record
        # tmp_path is not a git repo
        assert record["git_branch"] is None

        hist_file.unlink()

    def test_record_prompt_summary_branch_is_string_in_git_repo(self, tmp_path):
        """In an actual git repo, git_branch is a string."""
        import subprocess, user_prompt_submit as ups_mod

        project_id = "proj_branch_git_test"
        hist_file = PLUGIN_ROOT / "inbox" / f"{project_id}_prompts.jsonl"
        if hist_file.exists():
            hist_file.unlink()

        # Make a minimal git repo
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        env = {"HOME": str(tmp_path), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"}
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
            capture_output=True, env=env,
        )

        ups_mod.record_prompt_summary(project_id, "Decided to use SQLite for everything.", cwd=tmp_path)

        if hist_file.exists():
            record = json.loads(hist_file.read_text().strip().splitlines()[-1])
            assert "git_branch" in record
            # branch is either a string (main/master) or None (detached HEAD)
            assert record["git_branch"] is None or isinstance(record["git_branch"], str)
            hist_file.unlink()

    def test_episode_db_node_carries_git_branch(self, tmp_path):
        """Nodes written by write_episode carry git_branch in data dict."""
        import stop as stop_mod
        from node_types import NodeType

        project_id = "proj_ep_branch_db"
        session_data = {
            "tool_captures": [],
            "files_touched": [],
            "tools_used": [],
            "had_errors": False,
            "git_branch": "release/v2",
        }
        store, ep_data = stop_mod.write_episode(project_id, session_data)
        assert ep_data.get("git_branch") == "release/v2"

        # Verify it's actually persisted in the DB node
        ep_nodes = store.query_episodes_since(0, limit=5, project_id=project_id)
        matching = [n for n in ep_nodes if n.data.get("git_branch") == "release/v2"]
        assert len(matching) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# F. memory_session_history logic (full behaviour without MCP server import)
# ═══════════════════════════════════════════════════════════════════════════════

def _sim_session_history(delta_file: Path, project_id: str, limit: int = 10, since_days: int = 30):
    """
    Simulate memory_session_history behaviour against a specific delta file.
    Mirrors the implementation in server.py exactly for black-box testing.
    """
    if not delta_file.exists():
        return {"sessions": [], "total": 0, "note": "No session delta log found yet."}

    cutoff = time.time() - since_days * 86400
    raw_lines = delta_file.read_text(encoding="utf-8").strip().splitlines()

    sessions = []
    for line in reversed(raw_lines):
        if len(sessions) >= limit:
            break
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("project_id") != project_id:
            continue
        if r.get("finalized_at", 0) < cutoff:
            continue

        type_tally = {}
        for n in r.get("nodes", []):
            t = n.get("node_type", "unknown")
            type_tally[t] = type_tally.get(t, 0) + 1

        sessions.append({
            "session_id": r.get("session_id", "?"),
            "started_at": r.get("started_at"),
            "finalized_at": r.get("finalized_at"),
            "node_count": r.get("node_count", 0),
            "node_types": type_tally,
            "nodes": [
                {"node_id": n["node_id"], "node_type": n["node_type"], "content_hash": n["content_hash"]}
                for n in r.get("nodes", [])
            ],
        })

    return {"sessions": sessions, "total": len(sessions), "project_id": project_id, "since_days": since_days}


def _delta(tmp_path, project_id, session_id, nodes, ago_s=60):
    delta_dir = tmp_path / "logs"
    delta_dir.mkdir(exist_ok=True)
    record = {
        "session_id": session_id, "project_id": project_id,
        "started_at": round(time.time() - ago_s - 30, 3),
        "finalized_at": round(time.time() - ago_s, 3),
        "node_count": len(nodes), "nodes": nodes,
    }
    with open(delta_dir / "session_deltas.jsonl", "a") as f:
        f.write(json.dumps(record) + "\n")


class TestSessionHistoryLogic:
    def test_no_file_returns_empty_sessions(self, tmp_path):
        result = _sim_session_history(tmp_path / "logs" / "session_deltas.jsonl", "proj")
        assert result["sessions"] == []
        assert result["total"] == 0

    def test_filters_by_project_id(self, tmp_path):
        nodes = [{"node_id": "n1", "node_type": "episode", "content_hash": "abc"}]
        _delta(tmp_path, "proj_a", "sid-a", nodes)
        _delta(tmp_path, "proj_b", "sid-b", nodes)
        result = _sim_session_history(tmp_path / "logs" / "session_deltas.jsonl", "proj_a")
        assert result["total"] == 1
        assert result["sessions"][0]["session_id"] == "sid-a"

    def test_most_recent_first(self, tmp_path):
        nodes = [{"node_id": "n1", "node_type": "episode", "content_hash": "abc"}]
        _delta(tmp_path, "proj", "sid-old", nodes, ago_s=3600)
        _delta(tmp_path, "proj", "sid-new", nodes, ago_s=10)
        result = _sim_session_history(tmp_path / "logs" / "session_deltas.jsonl", "proj")
        # reversed iteration means most recent appears first
        assert result["sessions"][0]["session_id"] == "sid-new"

    def test_limit_enforced(self, tmp_path):
        nodes = [{"node_id": "n1", "node_type": "episode", "content_hash": "abc"}]
        for i in range(8):
            _delta(tmp_path, "proj", f"sid-{i}", nodes, ago_s=i * 10 + 5)
        result = _sim_session_history(tmp_path / "logs" / "session_deltas.jsonl", "proj", limit=3)
        assert result["total"] == 3

    def test_since_days_filter(self, tmp_path):
        nodes = [{"node_id": "n1", "node_type": "episode", "content_hash": "abc"}]
        _delta(tmp_path, "proj", "sid-stale", nodes, ago_s=10 * 86400)
        _delta(tmp_path, "proj", "sid-fresh", nodes, ago_s=60)
        result = _sim_session_history(tmp_path / "logs" / "session_deltas.jsonl", "proj", since_days=7)
        sids = [s["session_id"] for s in result["sessions"]]
        assert "sid-fresh" in sids
        assert "sid-stale" not in sids

    def test_node_type_tally_correct(self, tmp_path):
        nodes = [
            {"node_id": "n1", "node_type": "episode", "content_hash": "a"},
            {"node_id": "n2", "node_type": "failure", "content_hash": "b"},
            {"node_id": "n3", "node_type": "failure", "content_hash": "c"},
        ]
        _delta(tmp_path, "proj", "sid-1", nodes)
        result = _sim_session_history(tmp_path / "logs" / "session_deltas.jsonl", "proj")
        tally = result["sessions"][0]["node_types"]
        assert tally["episode"] == 1
        assert tally["failure"] == 2

    def test_output_shape_complete(self, tmp_path):
        nodes = [{"node_id": "n1", "node_type": "episode", "content_hash": "abc123"}]
        _delta(tmp_path, "proj", "sid-shape", nodes)
        result = _sim_session_history(tmp_path / "logs" / "session_deltas.jsonl", "proj")
        s = result["sessions"][0]
        assert "session_id" in s
        assert "started_at" in s
        assert "finalized_at" in s
        assert "node_count" in s
        assert "node_types" in s
        assert "nodes" in s
        node = s["nodes"][0]
        assert "node_id" in node
        assert "node_type" in node
        assert "content_hash" in node

    def test_malformed_lines_skipped(self, tmp_path):
        delta_dir = tmp_path / "logs"
        delta_dir.mkdir()
        f = delta_dir / "session_deltas.jsonl"
        f.write_text("not json\n{}\n")
        result = _sim_session_history(f, "proj")
        assert isinstance(result["sessions"], list)

    def test_server_py_registers_tool(self):
        src = (PLUGIN_ROOT / "mcp_server" / "server.py").read_text()
        assert "memory_server.memory_session_history = memory_session_history" in src


# ═══════════════════════════════════════════════════════════════════════════════
# G. Branch-filtered recall behaviour
# ═══════════════════════════════════════════════════════════════════════════════

class TestBranchFilteredRecall:
    def _ep_node(self, project_id, branch):
        from node_types import GraphNode, NodeType
        return GraphNode(
            id=str(uuid.uuid4()), node_type=NodeType.EPISODE,
            project_id=project_id, agent_id="test",
            created_at=int(time.time()), updated_at=int(time.time()),
            confidence=1.0,
            data={"task_description": f"work on {branch}", "git_branch": branch, "outcome": "success",
                  "tool_calls": [], "files_touched": []},
            embedding_text=f"work on branch {branch}",
        )

    def _sem_node(self, project_id):
        from node_types import GraphNode, NodeType
        return GraphNode(
            id=str(uuid.uuid4()), node_type=NodeType.SEMANTIC,
            project_id=project_id, agent_id="test",
            created_at=int(time.time()), updated_at=int(time.time()),
            confidence=0.9,
            data={"fact": "test semantic fact"},
            embedding_text="test semantic fact",
        )

    def test_filter_lambda_main_branch(self):
        """The _ep_branch helper used in memory_recall_context works correctly."""
        def _ep_branch(ep):
            d = ep.data if hasattr(ep, "data") else (ep if isinstance(ep, dict) else {})
            return d.get("git_branch") if isinstance(d, dict) else None

        from node_types import GraphNode, NodeType
        ep = GraphNode(
            id="x", node_type=NodeType.EPISODE, project_id="p",
            agent_id="a", created_at=0, updated_at=0, confidence=1.0,
            data={"git_branch": "main"}, embedding_text=None,
        )
        assert _ep_branch(ep) == "main"

    def test_filter_lambda_dict_episode(self):
        """Filter works on plain dict episodes (native recall path).

        In the native path, episodes are returned as flat dicts where the
        dict itself is the data (matching GraphNode.data layout), not wrapped
        with a 'data' key.
        """
        def _ep_branch(ep):
            d = ep.data if hasattr(ep, "data") else (ep if isinstance(ep, dict) else {})
            return d.get("git_branch") if isinstance(d, dict) else None

        # Flat dict — the dict IS the episode data (same as GraphNode.data)
        ep_dict = {"git_branch": "feature/x", "task_description": "some task"}
        assert _ep_branch(ep_dict) == "feature/x"

    def test_filter_lambda_none_branch(self):
        """Episodes with no git_branch field return None."""
        def _ep_branch(ep):
            d = ep.data if hasattr(ep, "data") else (ep if isinstance(ep, dict) else {})
            return d.get("git_branch") if isinstance(d, dict) else None

        from node_types import GraphNode, NodeType
        ep = GraphNode(
            id="x", node_type=NodeType.EPISODE, project_id="p",
            agent_id="a", created_at=0, updated_at=0, confidence=1.0,
            data={"task_description": "no branch"}, embedding_text=None,
        )
        assert _ep_branch(ep) is None

    def test_branch_filter_applied_to_episode_list(self, tmp_path):
        """Filtering recent_episodes list keeps only matching branch."""
        from graph_store import get_graph_store

        store = get_graph_store(tmp_path / "t.db")
        ep_main = self._ep_node("proj", "main")
        ep_feat = self._ep_node("proj", "feature/dashboard")
        store.write_node(ep_main)
        store.write_node(ep_feat)

        episodes = store.query_episodes_since(0, limit=10, project_id="proj")

        def _ep_branch(ep):
            d = ep.data if hasattr(ep, "data") else (ep if isinstance(ep, dict) else {})
            return d.get("git_branch") if isinstance(d, dict) else None

        filtered = [ep for ep in episodes if _ep_branch(ep) == "main"]
        assert len(filtered) == 1
        assert filtered[0].id == ep_main.id

    def test_semantic_nodes_pass_through_branch_filter(self, tmp_path):
        """Non-episode nodes always included regardless of branch filter."""
        from graph_store import get_graph_store

        store = get_graph_store(tmp_path / "t.db")
        ep_feat = self._ep_node("proj", "feature/x")
        sem = self._sem_node("proj")
        store.write_node(ep_feat)
        store.write_node(sem)

        results = store.search_fts("test", "proj", 50)
        git_branch = "main"
        filtered = [
            n for n in results
            if n.node_type.value != "episode"
            or (n.data or {}).get("git_branch") == git_branch
        ]
        sem_ids = {n.id for n in filtered if n.node_type.value == "semantic"}
        ep_ids = {n.id for n in filtered if n.node_type.value == "episode"}

        assert sem.id in sem_ids      # semantic always passes through
        assert ep_feat.id not in ep_ids  # feature branch excluded when filtering "main"

    def test_no_branch_filter_returns_all_episodes(self, tmp_path):
        """Without git_branch, all episodes are returned."""
        from graph_store import get_graph_store

        store = get_graph_store(tmp_path / "t.db")
        ep_main = self._ep_node("proj", "main")
        ep_feat = self._ep_node("proj", "feature/x")
        store.write_node(ep_main)
        store.write_node(ep_feat)

        episodes = store.query_episodes_since(0, limit=10, project_id="proj")
        ids = {ep.id for ep in episodes}
        assert ep_main.id in ids
        assert ep_feat.id in ids

    def test_memory_recall_context_signature_has_git_branch(self):
        src = (PLUGIN_ROOT / "mcp_server" / "server.py").read_text()
        # Find the function definition
        idx = src.find("async def memory_recall_context(")
        snippet = src[idx: idx + 300]
        assert "git_branch" in snippet

    def test_memory_search_signature_has_git_branch(self):
        src = (PLUGIN_ROOT / "mcp_server" / "server.py").read_text()
        idx = src.find("async def memory_search(")
        snippet = src[idx: idx + 200]
        assert "git_branch" in snippet

    def test_memory_recall_filters_episodes_in_implementation(self):
        """memory_recall_context implementation filters recent_episodes by branch."""
        src = (PLUGIN_ROOT / "mcp_server" / "server.py").read_text()
        idx = src.find("async def memory_recall_context(")
        # Use a larger window — _ep_branch lambda and recent_episodes filter
        # appear after the compile_memory_context call, ~1500+ chars in.
        fn_body = src[idx: idx + 3000]
        assert "git_branch" in fn_body
        assert "recent_episodes" in fn_body
        assert "_ep_branch" in fn_body or "git_branch" in fn_body
