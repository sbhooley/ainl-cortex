"""Cost-control hook wiring checks (static + gate logic)."""

from pathlib import Path

from hooks.shared.conversation_detection import is_conversation_only_turn

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def test_user_prompt_submit_wires_conversation_gate():
    src = (PLUGIN_ROOT / "hooks" / "user_prompt_submit.py").read_text(encoding="utf-8")
    assert "is_conversation_only_turn" in src
    assert 'conversation_only' in src
    assert "_skip_reason = \"conversation_only\"" in src or "_skip_reason = 'conversation_only'" in src


def test_ainl_detection_skips_conversation_turns():
    src = (PLUGIN_ROOT / "hooks" / "ainl_detection.py").read_text(encoding="utf-8")
    assert "is_conversation_only_turn" in src
    assert "return" in src  # early exit before suggest


def test_post_tool_use_records_tool_digest_metrics():
    src = (PLUGIN_ROOT / "hooks" / "post_tool_use.py").read_text(encoding="utf-8")
    assert "tool_digest_created" in src
    assert "trajectory_fingerprint" in src


def test_stop_output_compression_hook_present():
    src = (PLUGIN_ROOT / "hooks" / "stop.py").read_text(encoding="utf-8")
    assert "compress_output" in src
    assert "task_description_full" in src


def test_conversation_gate_skips_recall_for_thanks():
    assert is_conversation_only_turn("thanks")
    assert not is_conversation_only_turn("fix the bug in auth.py")


def test_startup_project_context_sync_wired():
    src = (PLUGIN_ROOT / "hooks" / "startup.py").read_text(encoding="utf-8")
    assert "sync_project_docs" in src


def test_server_registers_cost_mcp_tools():
    src = (PLUGIN_ROOT / "mcp_server" / "server.py").read_text(encoding="utf-8")
    assert "cortex_cost_snapshot" in src
    assert "ainl_promote_pattern" in src
    assert "memory_get_tool_outcome" in src
