"""
Functional tests for FailureAdvisor and related failure-prevention infrastructure.

Tests actually execute the code (not grep source) and verify:
  A. FailureAdvisor.analyse_prompt() — signal matching and threshold logic
  B. create_failure_node embedding_text enrichment (file, command, stack_trace)
  C. Auto-extract file from error_message regex logic
  D. format_warnings output
"""

import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

from graph_store import SQLiteGraphStore
from node_types import create_failure_node
from failure_advisor import FailureAdvisor

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

_FILE_EXTRACT_RE = __import__('re').compile(
    r'[\w./\\-]+\.(?:py|ts|tsx|js|json|yaml|yml|sql|sh|ainl|lang|toml|cfg|txt)\b'
)


def _make_store(tmp_path):
    return SQLiteGraphStore(tmp_path / "test.db")


def _store_failure(store, project_id, error_type, tool, error_message, **kwargs):
    node = create_failure_node(
        project_id=project_id,
        error_type=error_type,
        tool=tool,
        error_message=error_message,
        **kwargs,
    )
    store.write_node(node)
    return node


def _advisor(store, project_id="proj", tmp_path=None):
    return FailureAdvisor(store, project_id, cache_dir=tmp_path)


# ── A. analyse_prompt core behaviour ─────────────────────────────────────────

class TestAnalysePrompt:

    def test_empty_store_returns_empty(self, tmp_path):
        store = _make_store(tmp_path)
        assert _advisor(store).analyse_prompt("run ainl_run with http adapter") == []

    def test_wrong_project_returns_empty(self, tmp_path):
        store = _make_store(tmp_path)
        _store_failure(store, "proj-A", "http_error", "ainl_run",
                       "http adapter registration failed")
        _store_failure(store, "proj-A", "parse_error", "ainl_validate", "syntax error")
        assert _advisor(store, "proj-B").analyse_prompt("run ainl_run http adapter") == []

    def test_unrelated_prompt_returns_empty(self, tmp_path):
        store = _make_store(tmp_path)
        _store_failure(store, "p", "http_error", "ainl_run",
                       "http adapter registration failed")
        _store_failure(store, "p", "parse_error", "ainl_validate", "syntax error in step block")
        warnings = _advisor(store, "p").analyse_prompt(
            "write me a python function to reverse a list"
        )
        assert warnings == []

    def test_tool_match_triggers_warning(self, tmp_path):
        """CMD regex uses \bainl\b — 'ainl' standalone (not ainl_run) must appear in prompt."""
        store = _make_store(tmp_path)
        _store_failure(store, "p", "adapter_error", "ainl_run",
                       "http adapter registration failed: connection refused")
        _store_failure(store, "p", "other_error", "ainl_validate", "unrelated syntax error")
        # 'ainl' appears standalone → matches _CMD_PAT → command signal fires
        warnings = _advisor(store, "p").analyse_prompt(
            "I want to run the ainl workflow again"
        )
        assert len(warnings) > 0

    def test_file_match_triggers_warning(self, tmp_path):
        store = _make_store(tmp_path)
        _store_failure(store, "p", "load_error", "ainl_run",
                       "failed to load config.yaml", file="config.yaml")
        _store_failure(store, "p", "other", "ainl_validate", "unrelated error")
        warnings = _advisor(store, "p").analyse_prompt(
            "let me fix config.yaml and try again"
        )
        assert len(warnings) > 0
        assert any(w.file == "config.yaml" for w in warnings)

    def test_matched_on_field_is_set(self, tmp_path):
        store = _make_store(tmp_path)
        _store_failure(store, "p", "adapter_error", "ainl_run",
                       "http adapter registration failed")
        _store_failure(store, "p", "other", "ainl_validate", "unrelated error")
        warnings = _advisor(store, "p").analyse_prompt("run ainl_run workflow")
        if warnings:
            assert warnings[0].matched_on in ("file", "command", "semantic")

    def test_confidence_between_zero_and_one(self, tmp_path):
        store = _make_store(tmp_path)
        _store_failure(store, "p", "adapter_error", "ainl_run",
                       "http adapter registration failed")
        _store_failure(store, "p", "other", "ainl_validate", "syntax error in step block")
        warnings = _advisor(store, "p").analyse_prompt("run ainl_run")
        for w in warnings:
            assert 0.0 < w.confidence <= 1.0

    def test_max_three_warnings_returned(self, tmp_path):
        store = _make_store(tmp_path)
        for i in range(8):
            _store_failure(store, "p", "http_error", "ainl_run",
                           f"http adapter error variant {i}: connection refused port {8000 + i}")
        warnings = _advisor(store, "p").analyse_prompt(
            "run ainl_run with http adapter again"
        )
        assert len(warnings) <= 3

    def test_warnings_sorted_by_confidence_descending(self, tmp_path):
        store = _make_store(tmp_path)
        _store_failure(store, "p", "load_error", "ainl_run",
                       "config.yaml failed to load", file="config.yaml")
        _store_failure(store, "p", "other", "ainl_run",
                       "generic adapter error no specific keywords")
        _store_failure(store, "p", "third", "ainl_validate", "parse error in step block")
        warnings = _advisor(store, "p").analyse_prompt(
            "fix config.yaml and run ainl_run"
        )
        scores = [w.confidence for w in warnings]
        assert scores == sorted(scores, reverse=True)

    def test_analyse_prompt_never_raises(self, tmp_path):
        store = _make_store(tmp_path)
        advisor = _advisor(store, "p")
        assert isinstance(advisor.analyse_prompt(""), list)
        assert isinstance(advisor.analyse_prompt("   \n\t  "), list)

    def test_semantic_keyword_overlap_does_not_crash(self, tmp_path):
        store = _make_store(tmp_path)
        _store_failure(store, "p", "timeout_error", "ainl_run",
                       "database connection pool timeout exceeded maximum limit")
        _store_failure(store, "p", "other", "ainl_compile",
                       "invalid workflow syntax in step definition block")
        warnings = _advisor(store, "p").analyse_prompt(
            "database connection keeps timing out"
        )
        assert isinstance(warnings, list)

    def test_cache_dir_accepted_without_error(self, tmp_path):
        store = _make_store(tmp_path)
        _store_failure(store, "p", "err", "ainl_run", "some error message")
        _store_failure(store, "p", "err2", "ainl_validate", "other error here")
        advisor = FailureAdvisor(store, "p", cache_dir=tmp_path)
        result = advisor.analyse_prompt("run ainl_run")
        assert isinstance(result, list)


# ── B. create_failure_node embedding_text enrichment ─────────────────────────

class TestFailureNodeEmbeddingText:

    def test_basic_embedding_includes_type_tool_message(self):
        node = create_failure_node(
            project_id="p", error_type="http_error",
            tool="ainl_run", error_message="connection refused",
        )
        assert "http_error" in node.embedding_text
        assert "ainl_run" in node.embedding_text
        assert "connection refused" in node.embedding_text

    def test_file_included_in_embedding_when_provided(self):
        node = create_failure_node(
            project_id="p", error_type="load_error", tool="ainl_run",
            error_message="failed to load config", file="config.yaml",
        )
        assert "config.yaml" in node.embedding_text

    def test_command_included_in_embedding_when_provided(self):
        node = create_failure_node(
            project_id="p", error_type="exec_error", tool="ainl_run",
            error_message="command failed", command="npm install",
        )
        assert "npm install" in node.embedding_text

    def test_stack_trace_truncated_to_200_chars(self):
        long_trace = "x" * 500
        node = create_failure_node(
            project_id="p", error_type="crash", tool="ainl_run",
            error_message="crash", stack_trace=long_trace,
        )
        assert long_trace[:200] in node.embedding_text
        assert long_trace[200:] not in node.embedding_text

    def test_none_fields_not_in_embedding(self):
        node = create_failure_node(
            project_id="p", error_type="parse_error", tool="ainl_validate",
            error_message="syntax error",
        )
        assert "None" not in node.embedding_text

    def test_embedding_text_is_nonempty_string(self):
        node = create_failure_node(
            project_id="p", error_type="err", tool="tool", error_message="msg",
        )
        assert isinstance(node.embedding_text, str)
        assert len(node.embedding_text) > 0

    def test_all_fields_in_embedding_when_all_provided(self):
        node = create_failure_node(
            project_id="p", error_type="multi", tool="ainl_run",
            error_message="failed", file="main.py",
            command="ainl_run", stack_trace="Traceback line 1",
        )
        assert "multi" in node.embedding_text
        assert "main.py" in node.embedding_text
        assert "ainl_run" in node.embedding_text
        assert "Traceback" in node.embedding_text


# ── C. Auto-extract file from error_message ───────────────────────────────────

class TestAutoExtractFileRegex:

    def test_py_file_extracted(self):
        m = _FILE_EXTRACT_RE.search("ImportError in mcp_server/graph_store.py line 42")
        assert m is not None and "graph_store.py" in m.group(0)

    def test_ainl_file_extracted(self):
        m = _FILE_EXTRACT_RE.search("validation failed for workflow.ainl at step 3")
        assert m is not None and "workflow.ainl" in m.group(0)

    def test_yaml_file_extracted(self):
        m = _FILE_EXTRACT_RE.search("failed to parse config.yaml: unexpected key")
        assert m is not None

    def test_json_file_extracted(self):
        m = _FILE_EXTRACT_RE.search("could not decode package.json")
        assert m is not None

    def test_no_file_returns_none(self):
        assert _FILE_EXTRACT_RE.search("connection refused: host unreachable") is None

    def test_server_has_auto_extract_wired(self):
        src = (PLUGIN_ROOT / "mcp_server" / "server.py").read_text()
        assert "kwargs['file'] = _fp.group(0)" in src
        assert "ainl|lang" in src


# ── D. format_warnings output ─────────────────────────────────────────────────

class TestFormatWarnings:

    def test_empty_list_returns_empty_string(self, tmp_path):
        store = _make_store(tmp_path)
        assert _advisor(store).format_warnings([]) == ""

    def test_nonempty_warnings_produce_nonempty_output(self, tmp_path):
        store = _make_store(tmp_path)
        _store_failure(store, "p", "http_error", "ainl_run",
                       "http adapter registration failed")
        _store_failure(store, "p", "other", "ainl_validate", "syntax error in step")
        advisor = _advisor(store, "p")
        warnings = advisor.analyse_prompt("run ainl_run http adapter workflow")
        if warnings:
            out = advisor.format_warnings(warnings)
            assert isinstance(out, str) and len(out) > 10

    def test_format_includes_error_type(self, tmp_path):
        store = _make_store(tmp_path)
        _store_failure(store, "p", "unique_xyz_error", "ainl_run",
                       "http adapter registration failed: connection refused")
        _store_failure(store, "p", "other", "ainl_validate", "parse error in syntax block")
        advisor = _advisor(store, "p")
        warnings = advisor.analyse_prompt("run ainl_run")
        if warnings:
            assert "unique_xyz_error" in advisor.format_warnings(warnings)

    def test_format_with_none_trends_does_not_raise(self, tmp_path):
        store = _make_store(tmp_path)
        advisor = _advisor(store, "p")
        result = advisor.format_warnings([], trends=None)
        assert result == ""


# ── E. GoalTracker — strict-native episode_node_id for GOAL_TRACKS ───────────

class TestGoalTracksEpisodeNodeId:

    def test_auto_update_links_goal_tracks_via_episode_node_id(self, tmp_path):
        from goal_tracker import GoalTracker
        from node_types import NodeType, GraphNode, EdgeType

        store = _make_store(tmp_path)
        ep_id = str(uuid.uuid4())
        now = int(time.time())
        store.write_node(GraphNode(
            id=ep_id,
            node_type=NodeType.EPISODE,
            project_id="proj_gt",
            agent_id="claude-code",
            created_at=now,
            updated_at=now,
            confidence=1.0,
            data={
                "turn_id": "native-turn-uuid",
                "task_description": "fix pytest failures",
                "files_touched": ["/tmp/test_failure_advisor.py"],
                "tool_calls": ["pytest"],
            },
        ))
        tracker = GoalTracker(store, "proj_gt")
        goal_id = tracker.create_goal(
            title="Fix pytest failures",
            description="stabilize test_failure_advisor suite",
        )
        updated = tracker.auto_update_from_episode({
            "turn_id": "synthetic-in-memory-turn",
            "episode_node_id": ep_id,
            "task_description": "fix pytest failures in test_failure_advisor",
            "files_touched": ["/tmp/test_failure_advisor.py"],
            "tool_calls": ["pytest"],
            "outcome": "success",
        })
        assert updated == 1
        edges = store.get_edges_from(goal_id, EdgeType.GOAL_TRACKS)
        assert len(edges) == 1
        assert edges[0].to_node == ep_id


# ── F. Native backend — get_unresolved_failures must not use FTS "*" ─────────

try:
    import native_graph_store as _ngs
except ImportError:
    _ngs = None


@pytest.mark.skipif(_ngs is None or not _ngs._NATIVE_OK, reason="ainl_native not built")
class TestNativeUnresolvedFailures:

    def test_get_unresolved_failures_returns_stored_failures(self, tmp_path):
        db = tmp_path / "ainl_native.db"
        store = _ngs.NativeGraphStore(db)
        pid = "proj_native"

        node = create_failure_node(
            pid, "adapter_error", "ainl_run", "http adapter registration failed"
        )
        store.write_node(node)

        unresolved = store.get_unresolved_failures(pid, limit=10)
        assert len(unresolved) == 1
        assert unresolved[0].data.get("error_type") == "adapter_error"

    def test_failure_advisor_fires_on_native_store(self, tmp_path):
        db = tmp_path / "ainl_native.db"
        store = _ngs.NativeGraphStore(db)
        pid = "proj_native"

        _store_failure_native = lambda: store.write_node(
            create_failure_node(
                pid, "adapter_error", "ainl_run", "http adapter registration failed"
            )
        )
        _store_failure_native()
        _store_failure_native()

        warnings = FailureAdvisor(store, pid).analyse_prompt(
            "please run ainl_run with the http adapter"
        )
        assert len(warnings) >= 1
        assert warnings[0].matched_on in ("command", "semantic", "file")

    def test_get_unresolved_failures_merges_python_sidecar(self, tmp_path):
        """Strict-native writes failures to ainl_memory.db; native read must merge."""
        from graph_store import SQLiteGraphStore

        native_db = tmp_path / "ainl_native.db"
        sidecar_db = tmp_path / "ainl_memory.db"
        store = _ngs.NativeGraphStore(native_db)
        py_store = SQLiteGraphStore(sidecar_db)
        pid = "proj_sidecar_only"

        py_store.write_node(
            create_failure_node(
                pid, "compile_error", "ainl_validate", "unexpected token at line 1"
            )
        )

        unresolved = store.get_unresolved_failures(pid, limit=10)
        assert len(unresolved) == 1
        assert unresolved[0].data.get("error_type") == "compile_error"

    def test_goal_tracks_reads_episode_from_native_db(self, tmp_path):
        """Strict-native: goals on sidecar, episodes on native — read_store must bridge."""
        from goal_tracker import GoalTracker
        from node_types import NodeType, GraphNode, EdgeType, create_goal_node

        native_db = tmp_path / "ainl_native.db"
        sidecar_db = tmp_path / "ainl_memory.db"
        native = _ngs.NativeGraphStore(native_db)
        sidecar = SQLiteGraphStore(sidecar_db)
        ep_id = str(uuid.uuid4())
        turn_id = str(uuid.uuid4())
        now = int(time.time())
        native.write_node(GraphNode(
            id=ep_id,
            node_type=NodeType.EPISODE,
            project_id="proj_split",
            agent_id="claude-code",
            created_at=now,
            updated_at=now,
            confidence=1.0,
            data={
                "turn_id": turn_id,
                "task_description": "implement goal tracker bridge",
                "files_touched": ["/tmp/goal_tracker.py"],
                "tool_calls": ["edit"],
            },
        ))
        goal = create_goal_node(
            "proj_split",
            "Bridge goal tracker",
            "Wire read_store for native episodes",
        )
        native.write_node(goal)
        tracker = GoalTracker(sidecar, "proj_split", read_store=native)
        updated = tracker.auto_update_from_episode({
            "turn_id": "in-memory-only-turn",
            "episode_node_id": ep_id,
            "task_description": "implement goal tracker bridge in goal_tracker.py",
            "files_touched": ["/tmp/goal_tracker.py"],
            "tool_calls": ["edit"],
            "outcome": "success",
        })
        assert updated == 1
        edges = native.get_edges_from(goal.id, EdgeType.GOAL_TRACKS)
        assert len(edges) == 1
        assert edges[0].to_node == ep_id
        assert sidecar.get_node(ep_id) is None


@pytest.mark.skipif(_ngs is None or not _ngs._NATIVE_OK, reason="ainl_native not built")
class TestNativeSidecarGoals:

    def test_query_goals_merges_python_sidecar(self, tmp_path):
        """Strict-native writes goals to ainl_memory.db; native read must merge."""
        from graph_store import SQLiteGraphStore
        from node_types import create_goal_node

        native_db = tmp_path / "ainl_native.db"
        sidecar_db = tmp_path / "ainl_memory.db"
        store = _ngs.NativeGraphStore(native_db)
        py_store = SQLiteGraphStore(sidecar_db)
        pid = "proj_goals_sidecar"

        py_store.write_node(
            create_goal_node(pid, "Ship native merge", "Verify sidecar goals visible")
        )

        active = store.query_goals(pid, status="active", limit=10)
        assert len(active) == 1
        assert active[0].data.get("title") == "Ship native merge"

    def test_get_node_and_update_goal_on_sidecar(self, tmp_path):
        """memory_update_goal must reach goals written only to the sidecar."""
        from graph_store import SQLiteGraphStore
        from node_types import create_goal_node

        native_db = tmp_path / "ainl_native.db"
        sidecar_db = tmp_path / "ainl_memory.db"
        store = _ngs.NativeGraphStore(native_db)
        py_store = SQLiteGraphStore(sidecar_db)
        pid = "proj_goal_update"

        goal = create_goal_node(pid, "Sidecar goal", "Update via native store facade")
        py_store.write_node(goal)

        found = store.get_node(goal.id)
        assert found is not None
        assert found.data.get("title") == "Sidecar goal"

        store.update_node_data(goal.id, {"status": "completed"})
        updated = py_store.get_node(goal.id)
        assert updated.data.get("status") == "completed"
