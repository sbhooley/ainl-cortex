"""Hook MCP import bootstrap — recall injection depends on bare shims (Mac + Windows)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def test_ensure_hook_mcp_imports_loads_config():
    from hooks.shared.mcp_bootstrap import ensure_hook_mcp_imports

    assert ensure_hook_mcp_imports(force=True)
    from config import get_config

    cfg = get_config()
    assert cfg.get_memory_block() is not None


def test_all_bare_modules_register():
    from mcp_server.import_compat import (
        HOOK_RECALL_CRITICAL_MODULES,
        MCP_BARE_MODULES,
        MCP_BARE_MODULES_OPTIONAL,
        ensure_mcp_module_shims,
        hook_recall_imports_ok,
    )

    assert hook_recall_imports_ok(force=True)
    assert ensure_mcp_module_shims(force=True)
    for name in HOOK_RECALL_CRITICAL_MODULES:
        mod = __import__(name)
        assert mod is not None
    for name in MCP_BARE_MODULES:
        if name in MCP_BARE_MODULES_OPTIONAL:
            continue
        assert name in sys.modules or __import__(name) is not None


def test_user_prompt_submit_imports_config_like_hook():
    from hooks.shared.mcp_bootstrap import ensure_hook_mcp_imports

    ensure_hook_mcp_imports(force=True)
    from compression_pipeline import get_compression_pipeline

    pipeline = get_compression_pipeline()
    assert pipeline is not None


def test_plugin_root_windows_style_path(monkeypatch, tmp_path):
    from hooks.shared import mcp_bootstrap

    fake = tmp_path / "Users" / "me" / "plugins" / "ainl-cortex"
    (fake / "hooks" / "shared").mkdir(parents=True)
    (fake / "mcp_server").mkdir(parents=True)
    (fake / "hooks" / "shared" / "mcp_bootstrap.py").write_text(
        Path(mcp_bootstrap.__file__).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", r"C:\Users\me\plugins\ainl-cortex")
    root = mcp_bootstrap.plugin_root()
    assert root.name == "ainl-cortex" or str(root).replace("\\", "/").endswith("ainl-cortex")


def test_memory_brief_has_content_compressed_native_style():
    from recall_budget import memory_brief_has_content

    native_style = (
        "## Relevant Graph Memory\n\n**Recent Work:**\n"
        "- [2026-05-29] Session — tools: read; files: clip.md → success"
    )
    assert memory_brief_has_content(native_style)

    collapsed = (
        "## Memory (summary). - - Session — tools: bash → success (conf: 1.00). "
        "**Reusable patterns:**. - \"read-bash\": read → bash (fitness: 1.00)."
    )
    assert memory_brief_has_content(collapsed)


def test_user_prompt_submit_hook_runs_without_import_error():
    hook = PLUGIN_ROOT / "hooks" / "user_prompt_submit.py"
    payload = json.dumps(
        {
            "session_id": "test-session",
            "cwd": str(Path.home()),
            "prompt": "What resolution are the AINL_Clips video files in Downloads?",
            "hook_event_name": "UserPromptSubmit",
        }
    )
    env = {**dict(__import__("os").environ), "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT)}
    proc = subprocess.run(
        [sys.executable, str(hook)],
        input=payload,
        text=True,
        capture_output=True,
        cwd=str(PLUGIN_ROOT),
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "attempted relative import" not in (proc.stderr + proc.stdout).lower()
    out = json.loads(proc.stdout)
    assert "hookSpecificOutput" in out or "systemMessage" in out


def test_run_hook_user_prompt_submit_production_path():
    """hooks.json invokes scripts/run_hook.py — same path on Mac and Windows."""
    payload = json.dumps(
        {
            "session_id": "test-session",
            "cwd": str(Path.home()),
            "prompt": "Search graph memory for prior AINL_Clips ffmpeg export sessions.",
            "hook_event_name": "UserPromptSubmit",
        }
    )
    env = {**dict(__import__("os").environ), "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT)}
    proc = subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "scripts" / "run_hook.py"), "user_prompt_submit"],
        input=payload,
        text=True,
        capture_output=True,
        cwd=str(PLUGIN_ROOT),
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "attempted relative import" not in (proc.stderr + proc.stdout).lower()
    out = json.loads(proc.stdout)
    msg = out.get("systemMessage") or ""
    assert msg, "expected injected systemMessage from recall path"


def test_recall_backend_gating_python_vs_native():
    """Python store must not use stale native DB recall when ainl_native is importable."""
    src = (PLUGIN_ROOT / "hooks" / "user_prompt_submit.py").read_text(encoding="utf-8")
    assert "get_backend() == \"native\"" in src or "get_backend() == 'native'" in src


def test_operator_hook_import_check():
    from mcp_server.operator_checks import hook_mcp_imports_ok

    ok, msg = hook_mcp_imports_ok(PLUGIN_ROOT)
    assert ok, msg


def test_memory_recall_intent_bypasses_short_prompt_skip():
    src = (PLUGIN_ROOT / "hooks" / "user_prompt_submit.py").read_text(encoding="utf-8")
    assert "_memory_recall_intent" in src
    assert "prompt_too_short" in src


@pytest.mark.parametrize(
    "hook_name",
    ["stop", "post_tool_use", "pre_compact", "post_compact"],
)
def test_hooks_wire_mcp_bootstrap(hook_name: str):
    src = (PLUGIN_ROOT / "hooks" / f"{hook_name}.py").read_text(encoding="utf-8")
    assert "ensure_hook_mcp_imports" in src
