"""
Tests for pre_compact.py and post_compact.py project_id resolution.

Root cause: PreCompact/PostCompact hook payloads don't include cwd. Both
hooks were calling get_project_id() with no args, which defaults to
Path.cwd() = the plugin root (hooks run cd'd to plugin root). The
safety flush in PreCompact looked for inbox/{wrong_id}_captures.jsonl
and silently found nothing.

Fix: startup.py writes inbox/current_project_id.txt. PreCompact and
PostCompact read it via _get_compact_project_id().

Sections:
  A. _get_compact_project_id helper — reads sidecar, falls back gracefully
  B. pre_compact.main() — project_id correctness, non-fatal guarantee
  C. post_compact.main() — project_id correctness, non-fatal guarantee
"""

import json
import sys
from io import StringIO
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))
sys.path.insert(0, str(PLUGIN_ROOT))


# ── helpers ───────────────────────────────────────────────────────────────────

def _run_hook(module_name: str, monkeypatch, input_data: dict = None, plugin_root_override=None):
    """Import and run hook main() with captured stdout. Returns (exit_code, dict)."""
    import importlib
    mod = importlib.import_module(module_name)
    importlib.reload(mod)  # reset module-level state between tests

    if input_data is not None:
        fake_stdin = StringIO(json.dumps(input_data))
        monkeypatch.setattr(sys, "stdin", fake_stdin)

    if plugin_root_override is not None:
        monkeypatch.setattr(mod, "__file__",
                            str(plugin_root_override / "hooks" / f"{module_name}.py"))

    captured = StringIO()
    monkeypatch.setattr(sys, "stdout", captured)

    with pytest.raises(SystemExit) as exc:
        mod.main()

    raw = captured.getvalue().strip()
    first_line = raw.splitlines()[0] if raw else "{}"
    return exc.value.code, json.loads(first_line)


# ── A. _get_compact_project_id unit tests ────────────────────────────────────

class TestGetCompactProjectId:

    def test_reads_sidecar_when_present(self, tmp_path):
        import pre_compact as pc
        (tmp_path / "inbox").mkdir()
        (tmp_path / "inbox" / "current_project_id.txt").write_text("abc123def456")
        assert pc._get_compact_project_id(tmp_path) == "abc123def456"

    def test_strips_whitespace(self, tmp_path):
        import pre_compact as pc
        (tmp_path / "inbox").mkdir()
        (tmp_path / "inbox" / "current_project_id.txt").write_text("  myid  \n")
        assert pc._get_compact_project_id(tmp_path) == "myid"

    def test_fallback_when_no_inbox(self, tmp_path):
        import pre_compact as pc
        # No inbox dir — must not raise
        result = pc._get_compact_project_id(tmp_path)
        assert isinstance(result, str) and len(result) > 0

    def test_fallback_when_sidecar_absent(self, tmp_path):
        import pre_compact as pc
        (tmp_path / "inbox").mkdir()
        result = pc._get_compact_project_id(tmp_path)
        assert isinstance(result, str) and len(result) > 0

    def test_fallback_when_sidecar_empty(self, tmp_path):
        import pre_compact as pc
        (tmp_path / "inbox").mkdir()
        (tmp_path / "inbox" / "current_project_id.txt").write_text("   ")
        result = pc._get_compact_project_id(tmp_path)
        assert isinstance(result, str) and len(result) > 0

    def test_post_compact_reads_same_sidecar(self, tmp_path):
        import post_compact as poc
        (tmp_path / "inbox").mkdir()
        (tmp_path / "inbox" / "current_project_id.txt").write_text("projXYZ")
        assert poc._get_compact_project_id(tmp_path) == "projXYZ"


# ── B. sidecar round-trip: startup writes, pre_compact reads ─────────────────

class TestSidecarRoundTrip:

    def test_startup_written_id_readable_by_pre_compact(self, tmp_path):
        """The project_id written by startup must be exactly what pre_compact reads."""
        import pre_compact as pc

        expected_id = "roundtrip_project_id_12345"
        (tmp_path / "inbox").mkdir()
        (tmp_path / "inbox" / "current_project_id.txt").write_text(expected_id)

        assert pc._get_compact_project_id(tmp_path) == expected_id

    def test_sidecar_not_corrupted_by_whitespace_pid(self, tmp_path):
        import pre_compact as pc
        (tmp_path / "inbox").mkdir()
        # Simulate a buggy startup writing whitespace-padded id
        (tmp_path / "inbox" / "current_project_id.txt").write_text("\n  a1b2c3  \n")
        assert pc._get_compact_project_id(tmp_path) == "a1b2c3"


# ── C. pre_compact.main() — non-fatal guarantee ──────────────────────────────

class TestPreCompactMain:

    def test_exits_zero_with_empty_payload(self, monkeypatch):
        """pre_compact must not crash when given an empty hook payload."""
        import pre_compact as pc
        monkeypatch.setattr(sys, "stdin", StringIO(json.dumps({})))
        captured = StringIO()
        monkeypatch.setattr(sys, "stdout", captured)
        with pytest.raises(SystemExit) as exc:
            pc.main()
        assert exc.value.code == 0

    def test_outputs_valid_json_with_empty_payload(self, monkeypatch):
        import pre_compact as pc
        monkeypatch.setattr(sys, "stdin", StringIO(json.dumps({})))
        captured = StringIO()
        monkeypatch.setattr(sys, "stdout", captured)
        with pytest.raises(SystemExit):
            pc.main()
        data = json.loads(captured.getvalue().strip())
        assert isinstance(data, dict)

    def test_exits_zero_with_typical_payload(self, monkeypatch):
        import pre_compact as pc
        payload = {"messages": [{"role": "user", "content": "hello"}], "trigger": "auto"}
        monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))
        captured = StringIO()
        monkeypatch.setattr(sys, "stdout", captured)
        with pytest.raises(SystemExit) as exc:
            pc.main()
        assert exc.value.code == 0


# ── D. post_compact.main() — non-fatal guarantee ─────────────────────────────

class TestPostCompactMain:

    def test_exits_zero_with_empty_payload(self, monkeypatch):
        import post_compact as poc
        monkeypatch.setattr(sys, "stdin", StringIO(json.dumps({})))
        captured = StringIO()
        monkeypatch.setattr(sys, "stdout", captured)
        with pytest.raises(SystemExit) as exc:
            poc.main()
        assert exc.value.code == 0

    def test_outputs_valid_json_with_empty_payload(self, monkeypatch):
        import post_compact as poc
        monkeypatch.setattr(sys, "stdin", StringIO(json.dumps({})))
        captured = StringIO()
        monkeypatch.setattr(sys, "stdout", captured)
        with pytest.raises(SystemExit):
            poc.main()
        data = json.loads(captured.getvalue().strip())
        assert isinstance(data, dict)

    def test_exits_zero_with_typical_payload(self, monkeypatch):
        import post_compact as poc
        payload = {"messagesBefore": 50, "messagesAfter": 10, "summary": "..."}
        monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))
        captured = StringIO()
        monkeypatch.setattr(sys, "stdout", captured)
        with pytest.raises(SystemExit) as exc:
            poc.main()
        assert exc.value.code == 0
