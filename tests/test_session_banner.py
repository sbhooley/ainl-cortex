"""SessionStart banner compression copy."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))
if str(ROOT / "mcp_server") not in sys.path:
    sys.path.insert(0, str(ROOT / "mcp_server"))

from session_banner import (
    compression_status_from_config,
    build_main_banner,
    format_prior_session_context,
    format_stack_lines,
    _home_rel,
)


def test_compression_banner_lists_compresses_and_not():
    st = compression_status_from_config()
    text = st["line"]
    assert "~savings" not in text
    assert "(on)" not in text
    assert "compresses:" in text
    assert "not:" in text
    assert "SQLite" in text
    assert "MCP" in text


def test_build_main_banner_expands_compression_lines():
    st = compression_status_from_config()
    banner = build_main_banner(
        root=ROOT,
        backend="python",
        db_s="ready (ainl_memory.db)",
        project_id="abc123",
        isolation_mode="per_repo",
        git_repo=True,
        cwd=Path("/Users/clawdbot"),
        legacy_project_id="legacy999",
        compression_lines=st["lines"],
        ainl_ok=True,
        mcp_ok=True,
        mcp_detail="",
        native_status="skipped (python backend selected)",
        venv_file_status="appended to /tmp/sessionstart-hook-0.sh",
        expected_tools=31,
        bridge_line="not running — ArmaraOS daemon not found — start ArmaraOS to enable A2A",
    )
    assert "Graph Memory:" in banner
    assert "compresses:" in banner
    assert "Legacy fallback:" in banner
    assert "  • Stack:" in banner
    assert "AINL compiler (pip: ainativelang; import: compiler_v2)=yes" in banner
    assert "ainl_native (Rust bindings)=" in banner
    assert "MCP stack (same venv as server)=OK" in banner
    assert "venv on PATH (child processes)=" in banner
    assert "A2A bridge=" in banner
    assert "cwd: ~" in banner or "cwd: /" in banner
    assert banner.count("  • Compression:") == 1


def test_home_rel_shortens_paths():
    p = _home_rel(Path.home() / ".claude" / "plugins" / "ainl-cortex")
    assert p.startswith("~/")


def test_stack_lines_preserves_all_fields():
    stack = format_stack_lines(
        ainl_ok=False,
        ainl_heal_msg="pip install failed",
        native_status="skipped (python backend selected)",
        mcp_ok=False,
        mcp_detail="import error",
        venv_file_status="appended to /Users/clawdbot/.claude/session-env/abc/sessionstart-hook-0.sh",
        bridge_line="not running — ArmaraOS daemon not found — start ArmaraOS to enable A2A",
        expected_tools=31,
    )
    text = "\n".join(stack)
    assert "compiler_v2)=no (auto-heal:" in text
    assert "ainl_native (Rust bindings)=skipped" in text
    assert "MCP stack (same venv as server)=FAIL" in text
    assert "venv on PATH (child processes)=appended to ~/" in text
    assert "A2A bridge=not running" in text
    assert "~31 tools" in text
    assert len(stack) >= 2


def test_prior_session_context_box():
    text = format_prior_session_context(
        {
            "task_summary": "Session — tools: bash",
            "outcome": "success",
            "capture_count": 4,
            "tools_used": ["bash"],
            "semantic_tags": ["tooling", "formal"],
            "last_finalize": {"trajectory_steps": 74, "procedures_promoted": 0},
        },
        age_str="17h ago",
        freshness="Fresh",
        can_execute=True,
    )
    assert "PRIOR SESSION CONTEXT" in text
    assert "END PRIOR SESSION" in text
    assert "traj steps" in text
