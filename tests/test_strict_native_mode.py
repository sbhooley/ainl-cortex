"""
Tests for strict-native dual-write elimination (issue 6).

Strict-native = config.json memory.store_backend == "native" AND ainl_native
loaded successfully. In that mode the Python pipeline must skip:
  - write_episode (Rust _ainl_native.finalize_session creates the EPISODE)
  - write_persona (Rust EvolutionEngine drives persona)
  - write_patterns (Rust procedure learning drives procedurals)
  - write_semantics (Rust tag_turn drives semantics)
  - link_resolutions on the Python sidecar only (episode nodes live in Rust DB;
    RESOLVES edges to native episodes are best-effort)

Two carve-outs MUST still run on the Python sidecar:
  - write_failures (Rust derives only from trajectory steps; Python's
    _BASH_FAILURE_RE catches errors that never made it to a step record)
  - write_goals (Rust has no goal tracker yet)

These tests monkeypatch the writer functions in stop.py so we can assert which
ones were called without needing a real DB.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

# Make the plugin importable
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))
sys.path.insert(0, str(PLUGIN_ROOT / "mcp_server"))


@pytest.fixture(autouse=True)
def reset_config_cache():
    """Force shared.config to re-read for every test."""
    from shared import config as shared_config
    shared_config.reset_cache()
    yield
    shared_config.reset_cache()


def _import_stop_with_strict_native():
    """Re-import hooks.stop with _STRICT_NATIVE forced to True.

    The module reads _STRICT_NATIVE at import time, so we patch the
    is_strict_native helper before importing."""
    if "stop" in sys.modules:
        del sys.modules["stop"]
    with mock.patch("shared.config.is_strict_native", return_value=True):
        # Also patch the _ainl_native import so _NATIVE_OK is True
        fake_native = mock.MagicMock()
        fake_native.finalize_session.return_value = {
            "episode_id": "deadbeef-cafe-1111-2222-aaaaaaaaaaaa",
            "trajectory_steps": 0,
            "procedures_promoted": 0,
            "summary_saved": True,
        }
        with mock.patch.dict(sys.modules, {"ainl_native": fake_native}):
            import stop as stop_mod  # noqa: F401
            return stop_mod


def _import_stop_with_python_mode():
    """Re-import hooks.stop in pure-Python mode (no native, no strict).

    The CI venv may have a built ainl_native.so available; we force-import
    stop with both flags False so the test exercises the Python branch
    deterministically regardless of whether the native module is present."""
    if "stop" in sys.modules:
        del sys.modules["stop"]
    with mock.patch("shared.config.is_strict_native", return_value=False):
        import stop as stop_mod  # noqa: F401
    # Force both gates off after import, since the module may have picked up
    # a real ainl_native.so during its top-level try/except.
    stop_mod._STRICT_NATIVE = False
    stop_mod._NATIVE_OK = False
    stop_mod._ainl_native = None
    return stop_mod


class TestStrictNativeMode:
    """Validate the strict-native gating in finalize_session."""

    def test_strict_native_skips_python_episode_write(self):
        stop_mod = _import_stop_with_strict_native()
        assert stop_mod._STRICT_NATIVE is True

        session_data = {
            "tool_captures": [{"tool": "bash", "success": True}],
            "files_touched": ["/tmp/x.py"],
            "tools_used": ["bash"],
            "had_errors": False,
        }

        with mock.patch.object(stop_mod, "write_episode") as mock_write_episode, \
                mock.patch.object(stop_mod, "write_persona") as mock_write_persona, \
                mock.patch.object(stop_mod, "write_patterns") as mock_write_patterns, \
                mock.patch.object(stop_mod, "write_semantics") as mock_write_semantics, \
                mock.patch.object(stop_mod, "link_resolutions") as mock_link, \
                mock.patch.object(stop_mod, "write_failures") as mock_write_failures, \
                mock.patch.object(stop_mod, "write_goals") as mock_write_goals, \
                mock.patch.object(stop_mod, "_open_python_sidecar_store",
                                  return_value=mock.MagicMock()) as mock_open_sidecar, \
                mock.patch.object(stop_mod, "_native_finalize_session",
                                  return_value={"episode_id": "ok" * 8,
                                                "trajectory_steps": 0,
                                                "procedures_promoted": 0,
                                                "summary_saved": True}) as mock_native:
            stop_mod.finalize_session("proj_abc", session_data, PLUGIN_ROOT)

        # The Rust pipeline ran exactly once.
        mock_native.assert_called_once()

        # Python episode/persona/patterns/semantics skipped; resolutions on sidecar.
        mock_write_episode.assert_not_called()
        mock_write_persona.assert_not_called()
        mock_write_patterns.assert_not_called()
        mock_write_semantics.assert_not_called()
        mock_link.assert_called_once()

        # Python sidecar opened once for failures + goals + resolution linking.
        mock_open_sidecar.assert_called_once_with("proj_abc")

        # Carve-outs still ran.
        mock_write_failures.assert_called_once()
        mock_write_goals.assert_called_once()

    def test_python_mode_runs_full_pipeline(self):
        stop_mod = _import_stop_with_python_mode()
        assert stop_mod._STRICT_NATIVE is False
        assert stop_mod._NATIVE_OK is False

        session_data = {
            "tool_captures": [{"tool": "bash", "success": True}],
            "files_touched": ["/tmp/x.py"],
            "tools_used": ["bash"],
            "had_errors": False,
        }

        fake_store = mock.MagicMock()
        fake_episode = {
            "turn_id": "abc",
            "task_description": "x",
            "tool_calls": ["bash"],
            "files_touched": ["/tmp/x.py"],
            "outcome": "success",
            "duration_ms": 0,
            "git_commit": None,
        }

        with mock.patch.object(stop_mod, "write_episode",
                               return_value=(fake_store, fake_episode)) as mock_write_episode, \
                mock.patch.object(stop_mod, "write_persona") as mock_write_persona, \
                mock.patch.object(stop_mod, "write_patterns") as mock_write_patterns, \
                mock.patch.object(stop_mod, "write_semantics") as mock_write_semantics, \
                mock.patch.object(stop_mod, "link_resolutions") as mock_link, \
                mock.patch.object(stop_mod, "write_failures") as mock_write_failures, \
                mock.patch.object(stop_mod, "write_goals") as mock_write_goals, \
                mock.patch.object(stop_mod, "_native_finalize_session",
                                  return_value=None) as mock_native:
            stop_mod.finalize_session("proj_def", session_data, PLUGIN_ROOT)

        mock_write_episode.assert_called_once()
        mock_write_failures.assert_called_once()
        # _NATIVE_OK is False, so write_persona DOES run
        mock_write_persona.assert_called_once()
        mock_link.assert_called_once()
        mock_write_patterns.assert_called_once()
        mock_write_semantics.assert_called_once()
        mock_write_goals.assert_called_once()
        # Native helper still invoked but returns None because _NATIVE_OK=False
        mock_native.assert_not_called()

    def test_strict_native_per_prompt_flush_accumulates_without_native_finalize(self):
        stop_mod = _import_stop_with_strict_native()
        session_data = {
            "tool_captures": [{"tool": "bash", "success": True}],
            "files_touched": ["/tmp/x.py"],
            "tools_used": ["bash"],
            "had_errors": False,
        }

        with mock.patch.object(stop_mod, "drain_session_inbox", return_value=session_data), \
                mock.patch.object(stop_mod, "accumulate_into_pending") as mock_accum, \
                mock.patch.object(stop_mod, "_per_prompt_persist_failures") as mock_failures, \
                mock.patch.object(stop_mod, "_native_finalize_session") as mock_native, \
                mock.patch.object(stop_mod, "write_episode") as mock_write_episode, \
                mock.patch.object(stop_mod, "write_goals") as mock_write_goals:
            inbox = PLUGIN_ROOT / "inbox" / "proj_strict_test_captures.jsonl"
            inbox.parent.mkdir(parents=True, exist_ok=True)
            inbox.write_text('{"tool":"bash","success":true}\n')
            pending = PLUGIN_ROOT / "inbox" / "proj_strict_test_session_pending.json"
            try:
                count = stop_mod.flush_pending_captures("proj_strict_test")
            finally:
                if inbox.exists():
                    inbox.unlink()
                if pending.exists():
                    pending.unlink()
            assert count == 1
            mock_accum.assert_called_once()
            mock_failures.assert_called_once()
            mock_native.assert_not_called()
            mock_write_episode.assert_not_called()
            mock_write_goals.assert_not_called()

    def test_link_resolutions_runs_for_partial_outcome(self, tmp_path):
        stop_mod = _import_stop_with_strict_native()
        from graph_store import SQLiteGraphStore
        from node_types import create_failure_node

        store = SQLiteGraphStore(tmp_path / "ainl_memory.db")
        fail = create_failure_node(
            "proj", "tool_error", "bash", "err", file="/tmp/x.py"
        )
        store.write_node(fail)
        episode_data = {
            "turn_id": "t1",
            "outcome": "partial",
            "files_touched": ["/tmp/x.py"],
            "tool_calls": ["bash"],
            "task_description": "fixed with caveats",
        }
        linked = stop_mod.link_resolutions(store, "proj", episode_data)
        assert linked == 1
        updated = store.get_node(fail.id)
        assert updated.data.get("resolved_at")
        assert "partial" in (updated.data.get("resolution") or "").lower()

    def test_strict_native_finalize_runs_native_before_goals(self):
        """write_goals must see episode_node_id from Rust finalize_session."""
        stop_mod = _import_stop_with_strict_native()
        native_ep = "deadbeef-cafe-1111-2222-aaaaaaaaaaaa"
        order = []

        session_data = {
            "tool_captures": [{"tool": "bash", "success": True}],
            "files_touched": ["/tmp/x.py"],
            "tools_used": ["bash"],
            "had_errors": False,
        }

        def track_native(*_a, **_k):
            order.append("native")
            return {
                "episode_id": native_ep,
                "trajectory_steps": 0,
                "procedures_promoted": 0,
                "summary_saved": True,
            }

        def track_failures(*_a, **_k):
            order.append("failures")

        def track_goals(_store, _pid, episode_data, read_store=None):
            order.append("goals")
            assert episode_data.get("episode_node_id") == native_ep

        with mock.patch.object(stop_mod, "_open_python_sidecar_store",
                              return_value=mock.MagicMock()), \
                mock.patch.object(stop_mod, "_open_native_episode_store",
                              return_value=None), \
                mock.patch.object(stop_mod, "_native_finalize_session",
                              side_effect=track_native), \
                mock.patch.object(stop_mod, "write_failures",
                              side_effect=track_failures), \
                mock.patch.object(stop_mod, "write_goals",
                              side_effect=track_goals), \
                mock.patch.object(stop_mod, "_strict_native_link_after_finalize"):
            stop_mod.finalize_session("proj_order", session_data, PLUGIN_ROOT)

        assert order[0] == "native"
        assert "goals" in order
        assert order.index("native") < order.index("goals")

    def test_strict_native_link_resolutions_marks_sidecar_failure(self, tmp_path):
        """Successful strict-native sessions must mark matching sidecar failures resolved."""
        stop_mod = _import_stop_with_strict_native()
        from graph_store import SQLiteGraphStore
        from node_types import create_failure_node, NodeType

        project_id = "proj_link_res"
        sidecar_path = tmp_path / "graph_memory" / "ainl_memory.db"
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        store = SQLiteGraphStore(sidecar_path)

        fail = create_failure_node(
            project_id, "tool_error", "bash", "command failed", file="/tmp/x.py"
        )
        store.write_node(fail)

        session_data = {
            "tool_captures": [{"tool": "bash", "success": True, "file": "/tmp/x.py"}],
            "files_touched": ["/tmp/x.py"],
            "tools_used": ["bash"],
            "had_errors": False,
        }
        episode_data = stop_mod._build_episode_data_only(session_data)

        linked = stop_mod.link_resolutions(store, project_id, episode_data)
        assert linked == 1
        updated = store.get_node(fail.id)
        assert updated.data.get("resolved_at")
        assert updated.data.get("resolution")

    def test_link_resolutions_uses_episode_node_id_without_lookup(self, tmp_path):
        """Strict-native passes Rust episode_id so RESOLVES edges do not depend on turn_id."""
        stop_mod = _import_stop_with_strict_native()
        from graph_store import SQLiteGraphStore
        from node_types import create_failure_node, NodeType, GraphNode, EdgeType
        import time

        store = SQLiteGraphStore(tmp_path / "ainl_memory.db")
        ep_id = "native-episode-node-id"
        now = int(time.time())
        store.write_node(GraphNode(
            id=ep_id,
            node_type=NodeType.EPISODE,
            project_id="proj",
            agent_id="claude-code",
            created_at=now,
            updated_at=now,
            confidence=1.0,
            data={"turn_id": "other-turn", "files_touched": [], "tool_calls": []},
        ))
        fail = create_failure_node(
            "proj", "tool_error", "bash", "err", file="/tmp/x.py"
        )
        store.write_node(fail)

        episode_data = {
            "turn_id": "wrong-turn-id",
            "outcome": "success",
            "files_touched": ["/tmp/x.py"],
            "tool_calls": ["bash"],
            "task_description": "fixed it",
            "episode_node_id": ep_id,
        }
        linked = stop_mod.link_resolutions(store, "proj", episode_data)
        assert linked == 1
        edges = store.get_edges_to(fail.id, EdgeType.RESOLVES)
        assert len(edges) == 1
        assert edges[0].from_node == ep_id

    def test_link_resolutions_writes_resolves_edge_on_native_db(self, tmp_path):
        """RESOLVES must land on native when episode_node_id points at Rust DB."""
        stop_mod = _import_stop_with_strict_native()
        try:
            import native_graph_store as ngs
        except ImportError:
            pytest.skip("ainl_native not built")
        if not ngs.native_bindings_available():
            pytest.skip("ainl_native not built")

        from node_types import NodeType, GraphNode, EdgeType, create_failure_node
        import time

        native_db = tmp_path / "ainl_native.db"
        sidecar_db = tmp_path / "ainl_memory.db"
        native = ngs.NativeGraphStore(native_db)
        sidecar_path = sidecar_db.parent
        sidecar_path.mkdir(parents=True, exist_ok=True)

        ep_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        turn_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        now = int(time.time())
        native.write_node(GraphNode(
            id=ep_id,
            node_type=NodeType.EPISODE,
            project_id="proj_res_native",
            agent_id="claude-code",
            created_at=now,
            updated_at=now,
            confidence=1.0,
            data={
                "turn_id": turn_id,
                "files_touched": ["/tmp/x.py"],
                "tool_calls": ["bash"],
            },
        ))
        fail = create_failure_node(
            "proj_res_native", "tool_error", "bash", "err", file="/tmp/x.py"
        )
        native.write_node(fail)

        episode_data = {
            "turn_id": "wrong-turn",
            "outcome": "success",
            "files_touched": ["/tmp/x.py"],
            "tool_calls": ["bash"],
            "task_description": "fixed bash error",
            "episode_node_id": ep_id,
        }
        linked = stop_mod.link_resolutions(
            native,
            "proj_res_native",
            episode_data,
            episode_store=native,
        )
        assert linked == 1
        edges = native.get_edges_to(fail.id, EdgeType.RESOLVES)
        assert len(edges) == 1
        assert edges[0].from_node == ep_id
        unresolved = native.get_unresolved_failures("proj_res_native")
        assert not any(n.id == fail.id for n in unresolved)
        from graph_store import SQLiteGraphStore
        sidecar = SQLiteGraphStore(sidecar_db)
        sidecar_fail = sidecar.get_node(fail.id)
        assert sidecar_fail is not None
        assert sidecar_fail.data.get("resolved_at")

    def test_build_episode_data_only_does_not_persist(self):
        stop_mod = _import_stop_with_strict_native()
        session_data = {
            "tool_captures": [],
            "files_touched": ["/tmp/x.py"],
            "tools_used": ["bash"],
            "had_errors": True,
        }
        ed = stop_mod._build_episode_data_only(session_data)
        assert ed["outcome"] == "partial"
        assert ed["files_touched"] == ["/tmp/x.py"]
        assert ed["tool_calls"] == ["bash"]
        # Has a fresh turn_id but is not stored anywhere.
        assert isinstance(ed["turn_id"], str)


class TestSharedConfig:
    """Validate the shared/config.py helpers used by hooks."""

    def test_is_strict_native_requires_both_flags(self):
        from shared import config as shared_config
        with mock.patch.object(shared_config, "get_backend", return_value="native"):
            assert shared_config.is_strict_native(True) is True
            assert shared_config.is_strict_native(False) is False
        with mock.patch.object(shared_config, "get_backend", return_value="python"):
            assert shared_config.is_strict_native(True) is False

    def test_env_override_wins(self, monkeypatch):
        from shared import config as shared_config
        shared_config.reset_cache()
        monkeypatch.setenv("AINL_CORTEX_STORE_BACKEND", "native")
        assert shared_config.get_backend() == "native"
        monkeypatch.setenv("AINL_CORTEX_STORE_BACKEND", "python")
        assert shared_config.get_backend() == "python"
