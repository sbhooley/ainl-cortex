"""
Tests for the three production gaps addressed after analyst review:
  1. Deduplication — identical failures must not create duplicate nodes
  2. AINL auto-capture — ainl_run/ainl_validate errors captured from result JSON
  3. MCP schema — optional fields present and correctly described
"""

import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))


# ── 1. Deduplication ──────────────────────────────────────────────────────────

from node_types import failure_content_id, create_failure_node
from graph_store import get_graph_store


def test_failure_content_id_is_deterministic():
    id1 = failure_content_id("proj", "adapter_error", "ainl_run", "http failed")
    id2 = failure_content_id("proj", "adapter_error", "ainl_run", "http failed")
    assert id1 == id2


def test_failure_content_id_differs_by_error_type():
    a = failure_content_id("proj", "adapter_error", "ainl_run", "msg")
    b = failure_content_id("proj", "compile_error", "ainl_run", "msg")
    assert a != b


def test_failure_content_id_differs_by_project():
    a = failure_content_id("proj_a", "adapter_error", "ainl_run", "msg")
    b = failure_content_id("proj_b", "adapter_error", "ainl_run", "msg")
    assert a != b


def test_failure_content_id_prefix():
    fid = failure_content_id("p", "e", "t", "m")
    assert fid.startswith("fail-")


def test_failure_content_id_truncates_long_message():
    short_msg = "x" * 200
    long_msg  = "x" * 500
    # Both should hash the same (message capped at 200 chars)
    assert failure_content_id("p", "e", "t", short_msg) == failure_content_id("p", "e", "t", long_msg)


def test_write_node_deduplicates_identical_failures(tmp_path):
    db = tmp_path / "test.db"
    store = get_graph_store(db)
    pid = "proj"

    def _make_and_write():
        node = create_failure_node(pid, "adapter_error", "ainl_run", "http failed")
        node.id = failure_content_id(pid, "adapter_error", "ainl_run", "http failed")
        store.write_node(node)

    _make_and_write()
    _make_and_write()
    _make_and_write()

    failures = store.get_unresolved_failures(pid, limit=100)
    assert len(failures) == 1, f"Expected 1 failure node, got {len(failures)}"


def test_write_node_distinct_errors_not_deduplicated(tmp_path):
    db = tmp_path / "test.db"
    store = get_graph_store(db)
    pid = "proj"

    for msg in ("http failed", "compile error in workflow", "timeout on solana"):
        node = create_failure_node(pid, "error", "ainl_run", msg)
        node.id = failure_content_id(pid, "error", "ainl_run", msg)
        store.write_node(node)

    failures = store.get_unresolved_failures(pid, limit=100)
    assert len(failures) == 3


# ── 2. AINL auto-capture ──────────────────────────────────────────────────────

from post_tool_use import extract_tool_capture, _is_ainl_tool


def test_is_ainl_tool_bare():
    assert _is_ainl_tool("ainl_run")
    assert _is_ainl_tool("ainl_validate")
    assert _is_ainl_tool("ainl_compile")
    assert _is_ainl_tool("ainl_security_report")


def test_is_ainl_tool_with_mcp_prefix():
    assert _is_ainl_tool("mcp__ainl-cortex__ainl_run")
    assert _is_ainl_tool("ainl-cortex__ainl_validate")


def test_is_ainl_tool_false_for_other():
    assert not _is_ainl_tool("bash")
    assert not _is_ainl_tool("read")
    assert not _is_ainl_tool("memory_store_episode")


def test_ainl_run_adapter_error_captured():
    result = {
        "error_kind": "adapter_registration_error",
        "primary_diagnostic": "http adapter registration failed: connection refused",
        "source_path": "intelligence/fetch.ainl",
    }
    capture = extract_tool_capture("ainl_run", {}, result)
    assert capture["success"] is False
    assert capture["ainl_error_kind"] == "adapter_registration_error"
    assert "http adapter" in capture["error"]
    assert capture["file"] == "intelligence/fetch.ainl"


def test_ainl_validate_compile_error_captured():
    result = {
        "error_kind": "compile_error",
        "primary_diagnostic": "unexpected token THEN at line 5",
    }
    capture = extract_tool_capture("ainl_validate", {}, result)
    assert capture["success"] is False
    assert capture["ainl_error_kind"] == "compile_error"


def test_ainl_run_empty_source_not_captured():
    """empty_source is a user input issue, not a runtime failure to remember."""
    result = {"error_kind": "empty_source", "tool_call_error": False}
    capture = extract_tool_capture("ainl_run", {}, result)
    assert capture["success"] is True


def test_ainl_run_path_not_found_not_captured():
    result = {"error_kind": "path_not_found"}
    capture = extract_tool_capture("ainl_run", {"path": "missing.ainl"}, result)
    assert capture["success"] is True


def test_ainl_run_success_not_captured():
    result = {"status": "ok", "output": {"result": 42}}
    capture = extract_tool_capture("ainl_run", {}, result)
    assert capture["success"] is True


def test_ainl_mcp_prefix_tool_error_captured():
    result = {"type": "tool_error", "error": "MCP connection lost"}
    capture = extract_tool_capture("mcp__ainl-cortex__ainl_run", {}, result)
    assert capture["success"] is False


def test_ainl_capture_file_falls_back_to_input_path():
    """When source_path absent in result, fall back to path from tool_input."""
    result = {"error_kind": "runtime_error", "primary_diagnostic": "execution failed"}
    tool_input = {"path": "workflows/my.ainl"}
    capture = extract_tool_capture("ainl_run", tool_input, result)
    assert capture["file"] == "workflows/my.ainl"


# ── 3. MCP schema ─────────────────────────────────────────────────────────────

def _get_store_failure_schema():
    """Extract memory_store_failure inputSchema from server tool list."""
    # Parse the server module without starting the full MCP server
    import ast, textwrap
    server_path = Path(__file__).parent.parent / "mcp_server" / "server.py"
    source = server_path.read_text()
    # Find the inputSchema dict for memory_store_failure via simple JSON extraction
    marker = '"memory_store_failure"'
    idx = source.find(marker)
    assert idx != -1, "memory_store_failure tool definition not found"
    # Look for properties block after the marker
    props_start = source.find('"properties"', idx)
    # Return the substring for inspection
    return source[props_start: props_start + 1500]


def test_schema_exposes_file_field():
    schema_text = _get_store_failure_schema()
    assert '"file"' in schema_text


def test_schema_exposes_command_field():
    schema_text = _get_store_failure_schema()
    assert '"command"' in schema_text


def test_schema_exposes_stack_trace_field():
    schema_text = _get_store_failure_schema()
    assert '"stack_trace"' in schema_text


def test_schema_exposes_resolution_field():
    schema_text = _get_store_failure_schema()
    assert '"resolution"' in schema_text


def test_schema_required_fields_unchanged():
    schema_text = _get_store_failure_schema()
    for field in ("project_id", "error_type", "tool", "error_message"):
        assert f'"{field}"' in schema_text
