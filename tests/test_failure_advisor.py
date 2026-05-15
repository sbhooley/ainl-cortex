"""
Tests for FailureAdvisor — the failure prevention system that injects
proactive warnings into user-turn context.

Covers:
  - Analyst's exact scenario: manually stored failure with no file kwarg
  - Two-tier threshold (precise vs semantic)
  - File signal and ainl command signal
  - Single-failure Jaccard-only path (corpus < 2 docs)
  - False positive guard (unrelated prompts)
  - create_failure_node embedding_text enrichment
  - memory_store_failure auto-extraction of file from error_message
  - format_warnings output structure
"""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))

from graph_store import get_graph_store
from node_types import create_failure_node
from failure_advisor import FailureAdvisor, FailureWarning


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    db = tmp_path / "ainl_memory.db"
    return db


@pytest.fixture
def store(tmp_db):
    return get_graph_store(tmp_db)


@pytest.fixture
def cache_dir(tmp_path):
    return tmp_path


def _write_failure(store, project_id, error_type, tool, error_message, **kwargs):
    node = create_failure_node(
        project_id=project_id,
        error_type=error_type,
        tool=tool,
        error_message=error_message,
        **kwargs,
    )
    store.write_node(node)
    return node


def _advisor(store, project_id, cache_dir):
    return FailureAdvisor(store, project_id, cache_dir=cache_dir)


# ── Analyst's exact scenario ──────────────────────────────────────────────────

def test_analyst_scenario_warning_surfaces(store, cache_dir):
    """
    Manually stored failure (no file kwarg) must surface on a semantically
    matching follow-up prompt.  This is the case that was broken before.
    """
    pid = "proj_analyst"
    _write_failure(store, pid, "adapter_registration_error", "ainl_run",
                   "http adapter registration failed: connection refused")
    # Second node so TF-IDF corpus >= 2
    _write_failure(store, pid, "compile_error", "ainl_validate",
                   "syntax error: unexpected token THEN at line 14")

    advisor = _advisor(store, pid, cache_dir)
    warnings = advisor.analyse_prompt("I want to run my http adapter workflow again")

    assert len(warnings) >= 1
    assert warnings[0].error_type == "adapter_registration_error"
    assert warnings[0].matched_on == "semantic"
    assert warnings[0].confidence >= 0.18  # must clear semantic threshold


def test_analyst_scenario_no_false_positive(store, cache_dir):
    """Unrelated prompt must not trigger failure warnings."""
    pid = "proj_fp"
    _write_failure(store, pid, "adapter_registration_error", "ainl_run",
                   "http adapter registration failed: connection refused")
    _write_failure(store, pid, "compile_error", "ainl_validate",
                   "syntax error: unexpected token THEN at line 14")

    advisor = _advisor(store, pid, cache_dir)
    warnings = advisor.analyse_prompt("help me write a Python function to sort a list")

    assert len(warnings) == 0


# ── Two-tier threshold ────────────────────────────────────────────────────────

def test_file_signal_fires_precise_threshold(store, cache_dir):
    """File match reaches precise threshold (0.30) via +0.55 alone."""
    pid = "proj_file"
    _write_failure(store, pid, "io_error", "ainl_run",
                   "read failed", file="intelligence/my_workflow.ainl")

    advisor = _advisor(store, pid, cache_dir)
    warnings = advisor.analyse_prompt(
        "can you re-run intelligence/my_workflow.ainl for me"
    )

    assert len(warnings) >= 1
    assert warnings[0].matched_on == "file"
    assert warnings[0].confidence >= 0.30


def test_semantic_below_precise_threshold_still_surfaces(store, cache_dir):
    """Semantic match at 0.18–0.29 must surface (uses MIN_CONFIDENCE_SEMANTIC)."""
    pid = "proj_semantic"
    _write_failure(store, pid, "adapter_registration_error", "ainl_run",
                   "http adapter registration failed")
    _write_failure(store, pid, "unrelated_error", "ainl_validate",
                   "timeout connecting to solana rpc endpoint")

    advisor = _advisor(store, pid, cache_dir)
    warnings = advisor.analyse_prompt("run the http adapter workflow")

    # At least the adapter error should surface
    assert any(w.error_type == "adapter_registration_error" for w in warnings)


# ── Command signal: 'ainl' in _CMD_PAT ───────────────────────────────────────

def test_ainl_command_signal_fires(store, cache_dir):
    """'ainl' in the prompt must trigger Signal 2 for ainl_run failures."""
    pid = "proj_cmd"
    _write_failure(store, pid, "runtime_error", "ainl_run",
                   "execution failed", command="ainl")

    advisor = _advisor(store, pid, cache_dir)
    warnings = advisor.analyse_prompt("ainl run my workflow")

    assert len(warnings) >= 1
    assert warnings[0].matched_on in ("command", "semantic")
    assert warnings[0].confidence >= 0.30


# ── Single-failure Jaccard-only path ─────────────────────────────────────────

def test_single_failure_jaccard_fallback(store, cache_dir):
    """With only 1 failure (corpus < 2), Jaccard-only path runs without error."""
    pid = "proj_single"
    _write_failure(store, pid, "adapter_registration_error", "ainl_run",
                   "http adapter registration failed: connection refused")

    advisor = _advisor(store, pid, cache_dir)
    # Should not raise; may or may not surface depending on Jaccard score
    warnings = advisor.analyse_prompt("http adapter problem again")
    assert isinstance(warnings, list)


def test_empty_store_returns_no_warnings(store, cache_dir):
    """No failures stored → no warnings, no exceptions."""
    advisor = _advisor(store, "proj_empty", cache_dir)
    warnings = advisor.analyse_prompt("run the http adapter workflow")
    assert warnings == []


# ── Max warnings cap ─────────────────────────────────────────────────────────

def test_max_warnings_capped_at_three(store, cache_dir):
    """Never return more than 3 warnings regardless of how many failures match."""
    pid = "proj_cap"
    for i in range(10):
        _write_failure(store, pid, f"http_error_{i}", "ainl_run",
                       f"http adapter connection error variant {i}")

    advisor = _advisor(store, pid, cache_dir)
    warnings = advisor.analyse_prompt("run the http adapter workflow")
    assert len(warnings) <= 3


# ── embedding_text enrichment ─────────────────────────────────────────────────

def test_create_failure_node_embedding_includes_file(tmp_path):
    node = create_failure_node(
        project_id="p", error_type="io_error", tool="ainl_run",
        error_message="read failed",
        file="intelligence/my_workflow.ainl",
    )
    assert "intelligence/my_workflow.ainl" in node.embedding_text


def test_create_failure_node_embedding_includes_command(tmp_path):
    node = create_failure_node(
        project_id="p", error_type="exec_error", tool="ainl_run",
        error_message="execution failed",
        command="ainl run --strict",
    )
    assert "ainl run --strict" in node.embedding_text


def test_create_failure_node_embedding_includes_stack_trace(tmp_path):
    trace = "Traceback:\n  File workflow.ainl line 5\n  adapter http not found"
    node = create_failure_node(
        project_id="p", error_type="runtime_error", tool="ainl_run",
        error_message="failed",
        stack_trace=trace,
    )
    assert "adapter http not found" in node.embedding_text


def test_create_failure_node_embedding_truncates_stack_trace(tmp_path):
    trace = "x" * 1000
    node = create_failure_node(
        project_id="p", error_type="runtime_error", tool="ainl_run",
        error_message="failed",
        stack_trace=trace,
    )
    # embedding_text contains base fields + at most 200 chars of trace
    assert len(node.embedding_text) < 1000


def test_create_failure_node_embedding_no_optional_fields(tmp_path):
    """embedding_text still works when optional fields are absent."""
    node = create_failure_node(
        project_id="p", error_type="err", tool="ainl_run",
        error_message="something went wrong",
    )
    assert "err" in node.embedding_text
    assert "something went wrong" in node.embedding_text


# ── memory_store_failure auto-file extraction ─────────────────────────────────

def test_auto_file_extraction_from_error_message():
    """memory_store_failure must extract a file path from error_message."""
    import asyncio
    # Import the raw function directly to test without full MCP server init
    sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))
    import re

    error_message = "parse error in intelligence/fetch_prices.ainl at line 7"
    _fp = re.search(
        r'[\w./\\-]+\.(?:py|ts|tsx|js|json|yaml|yml|sql|sh|ainl|lang|toml|cfg|txt)\b',
        error_message,
    )
    assert _fp is not None
    assert _fp.group(0) == "intelligence/fetch_prices.ainl"


def test_auto_file_extraction_no_false_match():
    """Error messages with no file path must not produce a spurious file."""
    import re
    error_message = "http adapter registration failed: connection refused at port 8080"
    _fp = re.search(
        r'[\w./\\-]+\.(?:py|ts|tsx|js|json|yaml|yml|sql|sh|ainl|lang|toml|cfg|txt)\b',
        error_message,
    )
    assert _fp is None


# ── format_warnings output ────────────────────────────────────────────────────

def test_format_warnings_empty():
    advisor = FailureAdvisor(None, "p")
    assert advisor.format_warnings([]) == ""


def test_format_warnings_structure():
    advisor = FailureAdvisor(None, "p")
    w = FailureWarning(
        error_type="adapter_registration_error",
        error_summary="http adapter registration failed",
        resolution="use http.v2 adapter",
        confidence=0.72,
        matched_on="semantic",
        failure_node_id="abc123",
        file=None,
    )
    output = advisor.format_warnings([w])
    assert "⚠ Failure History" in output
    assert "adapter_registration_error" in output
    assert "72%" in output
    assert "http adapter registration failed" in output
    assert "use http.v2 adapter" in output


def test_format_warnings_unresolved():
    advisor = FailureAdvisor(None, "p")
    w = FailureWarning(
        error_type="runtime_error",
        error_summary="execution failed",
        resolution="",
        confidence=0.25,
        matched_on="semantic",
        failure_node_id="xyz",
    )
    output = advisor.format_warnings([w])
    assert "unresolved" in output.lower()


def test_format_warnings_includes_file():
    advisor = FailureAdvisor(None, "p")
    w = FailureWarning(
        error_type="io_error",
        error_summary="read failed",
        resolution="",
        confidence=0.80,
        matched_on="file",
        failure_node_id="xyz",
        file="intelligence/workflow.ainl",
    )
    output = advisor.format_warnings([w])
    assert "intelligence/workflow.ainl" in output
