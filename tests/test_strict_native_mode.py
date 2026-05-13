"""
Tests for strict-native dual-write elimination (issue 6).

Strict-native = config.json memory.store_backend == "native" AND ainl_native
loaded successfully. In that mode the Python pipeline must skip:
  - write_episode (Rust _ainl_native.finalize_session creates the EPISODE)
  - write_persona (Rust EvolutionEngine drives persona)
  - write_patterns (Rust procedure learning drives procedurals)
  - write_semantics (Rust tag_turn drives semantics)
  - link_resolutions (depends on write_episode having run on the same store)

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

        # Python episode/persona/patterns/semantics/link_resolutions all skipped.
        mock_write_episode.assert_not_called()
        mock_write_persona.assert_not_called()
        mock_write_patterns.assert_not_called()
        mock_write_semantics.assert_not_called()
        mock_link.assert_not_called()

        # Python sidecar opened once for failures + goals.
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

    def test_strict_native_per_prompt_flush_skips_python_episode(self):
        stop_mod = _import_stop_with_strict_native()
        session_data = {
            "tool_captures": [{"tool": "bash", "success": True}],
            "files_touched": ["/tmp/x.py"],
            "tools_used": ["bash"],
            "had_errors": False,
        }

        with mock.patch.object(stop_mod, "drain_session_inbox", return_value=session_data), \
                mock.patch.object(stop_mod, "write_episode") as mock_write_episode, \
                mock.patch.object(stop_mod, "write_persona") as mock_write_persona, \
                mock.patch.object(stop_mod, "write_patterns") as mock_write_patterns, \
                mock.patch.object(stop_mod, "write_semantics") as mock_write_semantics, \
                mock.patch.object(stop_mod, "write_failures") as mock_write_failures, \
                mock.patch.object(stop_mod, "write_goals") as mock_write_goals, \
                mock.patch.object(stop_mod, "_open_python_sidecar_store",
                                  return_value=mock.MagicMock()), \
                mock.patch.object(stop_mod, "_native_finalize_session", return_value=None):
            # Touch an inbox file so flush_pending_captures gets past its early returns.
            inbox = PLUGIN_ROOT / "inbox" / "proj_strict_test_captures.jsonl"
            inbox.parent.mkdir(parents=True, exist_ok=True)
            inbox.write_text('{"tool":"bash","success":true}\n')
            try:
                count = stop_mod.flush_pending_captures("proj_strict_test")
            finally:
                # drain_session_inbox normally unlinks; we mocked it, so do it ourselves
                if inbox.exists():
                    inbox.unlink()
            # Drain returned 1 capture so we should have flushed.
            assert count == 1
            mock_write_episode.assert_not_called()
            mock_write_persona.assert_not_called()
            mock_write_patterns.assert_not_called()
            mock_write_semantics.assert_not_called()
            mock_write_failures.assert_called_once()
            mock_write_goals.assert_called_once()

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
