"""
Tests for bash failure detection in hooks/post_tool_use.py.

Covers:
  - tool_error type → failure (existing path, regression guard)
  - exit_code != 0 → failure
  - exit_code == 0 → success even when output contains failure-like text
  - git conflict output (CONFLICT) → failure
  - git fatal error → failure
  - compiler error: → failure
  - pytest FAILED → failure
  - git Aborting → failure
  - Permission denied → failure
  - command not found → failure
  - make error → failure
  - npm ERR! → failure
  - Python Traceback → failure
  - Normal output → success (no false positives)
  - Grep output containing "error:" words → NOT flagged (if exit_code=0 guards it)
  - Error snippet extraction from various result shapes (flat text, content string, content list)
  - extract_tool_capture integration for bash tool
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

from post_tool_use import _detect_bash_failure, _bash_output, extract_tool_capture


# ── _bash_output ──────────────────────────────────────────────────────────────

def test_bash_output_flat_text():
    assert _bash_output({"type": "text", "text": "hello"}) == "hello"


def test_bash_output_flat_error():
    assert _bash_output({"type": "tool_error", "error": "bad"}) == "bad"


def test_bash_output_content_string():
    assert _bash_output({"content": "hello"}) == "hello"


def test_bash_output_content_list():
    result = {"content": [{"type": "text", "text": "hello"}, {"type": "text", "text": " world"}]}
    assert _bash_output(result) == "hello\n world"


def test_bash_output_empty():
    assert _bash_output({}) == ""


# ── tool_error type ──────────────────────────────────────────────────────────

def test_tool_error_type_is_failure():
    result = {"type": "tool_error", "text": "Permission denied: /etc/passwd"}
    is_fail, snippet = _detect_bash_failure(result)
    assert is_fail is True
    assert snippet


def test_tool_error_snippet_from_text():
    result = {"type": "tool_error", "text": "some error occurred"}
    _, snippet = _detect_bash_failure(result)
    assert snippet == "some error occurred"


def test_tool_error_snippet_from_content():
    result = {"type": "tool_error", "content": "content error"}
    _, snippet = _detect_bash_failure(result)
    assert snippet == "content error"


# ── exit_code detection ───────────────────────────────────────────────────────

def test_nonzero_exit_code_is_failure():
    result = {"type": "text", "text": "something failed", "exit_code": 1}
    is_fail, _ = _detect_bash_failure(result)
    assert is_fail is True


def test_nonzero_exit_code_string_is_failure():
    result = {"type": "text", "text": "something failed", "exit_code": "2"}
    is_fail, _ = _detect_bash_failure(result)
    assert is_fail is True


def test_zero_exit_code_is_success():
    result = {"type": "text", "text": "error: found in output", "exit_code": 0}
    is_fail, _ = _detect_bash_failure(result)
    assert is_fail is False


def test_zero_exit_code_string_is_success():
    result = {"type": "text", "text": "FAILED something", "exit_code": "0"}
    is_fail, _ = _detect_bash_failure(result)
    assert is_fail is False


def test_exit_code_zero_skips_semantic_scan():
    """exit_code=0 must suppress pattern matching to prevent false positives."""
    result = {"exit_code": 0, "text": "CONFLICT found in search results\nfatal: stuff"}
    is_fail, _ = _detect_bash_failure(result)
    assert is_fail is False


def test_nonzero_exit_code_extracts_snippet():
    result = {"exit_code": 1, "text": "make: *** [all] Error 1\nBuild failed"}
    _, snippet = _detect_bash_failure(result)
    assert snippet  # non-empty


# ── semantic pattern detection ────────────────────────────────────────────────

class TestConflictPattern:
    def test_git_merge_conflict(self):
        output = "CONFLICT (content): Merge conflict in foo.py\nAborted"
        is_fail, snippet = _detect_bash_failure({"text": output})
        assert is_fail is True
        assert "CONFLICT" in snippet

    def test_git_rebase_conflict(self):
        output = "CONFLICT (modify/delete): bar.py deleted in HEAD\n"
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is True

    def test_conflict_not_at_line_start_no_match(self):
        # "CONFLICT" embedded mid-line — should NOT match
        output = "Checking for CONFLICT markers... none found"
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is False


class TestFatalPattern:
    def test_git_fatal(self):
        output = "fatal: not a git repository (or any of the parent directories): .git"
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is True

    def test_fatal_mid_line_no_match(self):
        output = "Checking: fatal: prefix not at line start is ok"
        # "fatal: " doesn't start the line here — should NOT match
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is False

    def test_cmake_fatal(self):
        output = "fatal: CMakeLists.txt not found"
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is True


class TestErrorColonPattern:
    def test_compiler_error(self):
        output = "error: undefined reference to `main'\ncollect2: error: ld returned 1"
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is True

    def test_git_error(self):
        output = "error: Your local changes to the following files would be overwritten by merge"
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is True

    def test_error_not_at_line_start_no_match(self):
        output = "found 1 error: in module"
        # starts with "found", not "error:"
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is False


class TestFailedPattern:
    def test_pytest_failed(self):
        output = "FAILED tests/test_foo.py::test_bar - AssertionError"
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is True

    def test_make_failed(self):
        output = "FAILED\nBuild step exited with code 2"
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is True

    def test_failed_lowercase_no_match(self):
        output = "failed to connect (retrying)"
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is False

    def test_failed_mid_line_no_match(self):
        output = "All tests passed; 0 FAILED"
        # Embedded, not at line start
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is False


class TestAbortingPattern:
    def test_git_aborting(self):
        output = "Aborting\nYour index file is unmerged."
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is True

    def test_aborting_lowercase_no_match(self):
        output = "aborting merge"
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is False


class TestPermissionPattern:
    def test_permission_denied(self):
        output = "cat: /etc/shadow: Permission denied"
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is True

    def test_permission_denied_lowercase(self):
        output = "open: /etc/shadow: permission denied"
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is True


class TestCommandNotFoundPattern:
    def test_command_not_found(self):
        output = "zsh: command not found: foobar"
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is True

    def test_bash_command_not_found(self):
        output = "bash: nonexistent: command not found"
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is True


class TestMakePattern:
    def test_make_error(self):
        output = "make: *** [Makefile:42: all] Error 1"
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is True


class TestNpmPattern:
    def test_npm_error(self):
        output = "npm ERR! code ENOENT\nnpm ERR! syscall open"
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is True


class TestTracebackPattern:
    def test_python_traceback(self):
        output = "Traceback (most recent call last):\n  File 'foo.py', line 5, in <module>\nValueError: bad"
        is_fail, _ = _detect_bash_failure({"text": output})
        assert is_fail is True


# ── normal output → success (false positive guard) ───────────────────────────

def test_normal_ls_output_is_success():
    output = "total 48\ndrwxr-xr-x  2 user group 4096 May 13 10:00 .\n"
    is_fail, _ = _detect_bash_failure({"text": output})
    assert is_fail is False


def test_normal_echo_output_is_success():
    is_fail, _ = _detect_bash_failure({"text": "hello world\n"})
    assert is_fail is False


def test_git_log_output_is_success():
    output = "abc1234 Add feature\ndef5678 Fix bug\n"
    is_fail, _ = _detect_bash_failure({"text": output})
    assert is_fail is False


def test_pytest_all_passed_is_success():
    output = "collected 25 items\n\n...................... [100%]\n\n25 passed in 1.23s\n"
    is_fail, _ = _detect_bash_failure({"text": output})
    assert is_fail is False


def test_successful_build_output_is_success():
    output = "Compiling foo v0.1.0\nFinished release [optimized] target(s) in 2.34s\n"
    is_fail, _ = _detect_bash_failure({"text": output})
    assert is_fail is False


def test_empty_result_is_success():
    is_fail, snippet = _detect_bash_failure({})
    assert is_fail is False
    assert snippet == ""


# ── multiline output: snippet extraction ─────────────────────────────────────

def test_snippet_starts_at_matching_line():
    output = "Starting build...\nDone.\nCONFLICT (content): Merge conflict in foo.py\nOther output"
    _, snippet = _detect_bash_failure({"text": output})
    assert snippet.startswith("CONFLICT")


def test_snippet_within_500_chars():
    long_error = "error: " + "x" * 600
    _, snippet = _detect_bash_failure({"text": long_error})
    assert len(snippet) <= 500


# ── extract_tool_capture integration ─────────────────────────────────────────

def test_extract_bash_captures_conflict_failure():
    tool_input = {"command": "git stash pop"}
    tool_result = {"text": "CONFLICT (content): Merge conflict in hooks/post_tool_use.py\nAborted"}
    capture = extract_tool_capture("bash", tool_input, tool_result)
    assert capture["success"] is False
    assert "CONFLICT" in capture.get("error", "")


def test_extract_bash_captures_tool_error():
    tool_input = {"command": "rm /root/secret"}
    tool_result = {"type": "tool_error", "text": "Permission denied"}
    capture = extract_tool_capture("bash", tool_input, tool_result)
    assert capture["success"] is False


def test_extract_bash_success_no_error_key():
    tool_input = {"command": "echo hello"}
    tool_result = {"type": "text", "text": "hello\n"}
    capture = extract_tool_capture("bash", tool_input, tool_result)
    assert capture["success"] is True
    assert "error" not in capture


def test_extract_bash_nonzero_exit_code():
    tool_input = {"command": "false"}
    tool_result = {"exit_code": 1, "text": ""}
    capture = extract_tool_capture("bash", tool_input, tool_result)
    assert capture["success"] is False


def test_extract_bash_command_truncated_to_200():
    long_cmd = "echo " + "x" * 300
    capture = extract_tool_capture("bash", {"command": long_cmd}, {"text": "xxxxx\n"})
    assert len(capture["command"]) <= 200


def test_extract_bash_trajectory_step_reflects_failure(tmp_path, monkeypatch):
    """_buffer_traj_step must write success=False when bash fails."""
    import json
    from post_tool_use import _buffer_traj_step

    step_file = tmp_path / "steps.jsonl"
    inbox_dir = tmp_path

    # Monkeypatch the inbox dir so we write to tmp_path
    import post_tool_use as ptu
    original = ptu.Path
    monkeypatch.setattr(
        ptu, "Path",
        lambda *args, **kwargs: tmp_path if args == (__file__,) else original(*args, **kwargs)
    )

    failing_capture = {
        "type": "command",
        "success": False,
        "error": "CONFLICT (content): Merge conflict in foo.py",
    }

    # Write directly using the real inbox path logic
    step_file_real = (
        Path(__file__).resolve().parent.parent / "inbox" / "test_proj_traj_steps.jsonl"
    )
    step_file_real.parent.mkdir(parents=True, exist_ok=True)
    try:
        _buffer_traj_step("test_proj", "bash", failing_capture)
        steps = [json.loads(l) for l in step_file_real.read_text().strip().splitlines()]
        last_step = steps[-1]
        assert last_step["success"] is False
        assert last_step["adapter"] == "bash"
        assert last_step["error"] is not None
    finally:
        # Clean up test-injected step lines
        if step_file_real.exists():
            lines = step_file_real.read_text().strip().splitlines()
            cleaned = [l for l in lines if '"test_proj"' not in l]
            if cleaned:
                step_file_real.write_text('\n'.join(cleaned) + '\n')
            else:
                step_file_real.unlink()
