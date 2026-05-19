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
        bridge_line="not running — openfang not found",
    )
    assert "Graph Memory:" in banner
    assert "compresses:" in banner
    assert "Legacy fallback:" in banner
    assert "AINL Python tools" in banner
    assert "ainl_native" in banner
    assert "MCP stack" in banner
    assert "venv on PATH" in banner
    assert banner.count("  • Compression:") == 1


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
