#!/usr/bin/env python3
"""
PostToolUse Hook - Capture Execution

Captures tool outcomes and buffers for MCP server consolidation.
Follows AINL pattern: lightweight capture, async consolidation.
"""

import re
import sys
import json
from pathlib import Path
import time
import uuid

sys.path.insert(0, str(Path(__file__).parent))

from shared.project_id import get_project_id
from shared.logger import log_event, log_error, get_logger
from shared.config import is_strict_native

logger = get_logger("post_tool_use")

try:
    import ainl_native as _ainl_native
    _NATIVE_OK = True
except ImportError:
    _ainl_native = None
    _NATIVE_OK = False

# When strict-native is on, the mid-session flush must NOT run the Python
# episode/persona/patterns/semantics writers — Rust is the source of truth.
# See hooks/stop.py for the same gating used at end-of-session.
_STRICT_NATIVE = is_strict_native(_NATIVE_OK)


# Tool canonicalization (matches extractor.py)
TOOL_CANON = {
    'Bash': 'bash', 'Shell': 'bash', 'sh': 'bash',
    'Read': 'read', 'FileRead': 'read',
    'Edit': 'edit', 'FileEdit': 'edit',
    'Write': 'write', 'FileWrite': 'write',
    'Grep': 'grep', 'Search': 'grep',
    'Glob': 'glob',
    'WebSearch': 'web_search',
    'WebFetch': 'web_fetch',
}


def canonicalize_tool(tool_name: str) -> str:
    """Canonicalize tool name"""
    return TOOL_CANON.get(tool_name, tool_name.lower())


# Semantic failure patterns anchored to line starts to minimise false positives.
# Covers: git conflicts/fatal/abort, compiler errors, test failures, shell errors,
# permission errors, Python tracebacks, npm/make build errors.
_BASH_FAILURE_RE = re.compile(
    r'(?m)'
    r'(?:'
    r'^CONFLICT\b'                              # git merge/rebase/cherry-pick conflict
    r'|^fatal: '                                # git fatal, cmake fatal
    r'|^error: '                                # compiler errors, git errors, CLI errors
    r'|^FAILED\b'                               # pytest FAILED, make FAILED
    r'|^Aborting\b'                             # git aborting
    r'|: [Pp]ermission denied'                  # file/dir permission denied
    r'|: command not found'                      # unknown command
    r'|^make: \*\*\*'                           # make error prefix
    r'|^npm ERR!'                               # npm error prefix
    r'|^Traceback \(most recent call last\):'    # Python exception
    r')'
)


def _bash_output(result: dict) -> str:
    """Extract text from bash tool_result, handling flat and nested content formats."""
    if isinstance(result.get('text'), str):
        return result['text']
    if isinstance(result.get('error'), str):
        return result['error']
    content = result.get('content')
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(
            b.get('text', '') for b in content
            if isinstance(b, dict) and b.get('type') == 'text'
        )
    return ''


def _first_lines(text: str, max_len: int = 500) -> str:
    """Return the first non-empty lines of text up to max_len chars."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return '\n'.join(lines[:5])[:max_len]


def _detect_bash_failure(result: dict) -> tuple:
    """Return (is_failure: bool, error_snippet: str).

    Detection order (highest confidence first):
    1. Explicit tool_error type — Claude Code system-level error.
    2. Non-zero exit_code field — exit code provided by hook runtime.
    3. Semantic failure patterns — conservative regex on output text.

    If exit_code == 0 is explicitly present, semantic scanning is skipped
    to prevent false positives from output that legitimately contains error-
    like substrings (e.g. grep returning log lines).
    """
    # 1. Explicit tool error
    if result.get('type') == 'tool_error':
        return True, _bash_output(result)[:500]

    # 2. Explicit exit code
    exit_code = result.get('exit_code')
    if exit_code is not None:
        try:
            code = int(exit_code)
        except (TypeError, ValueError):
            code = None
        if code is not None:
            if code != 0:
                return True, _first_lines(_bash_output(result))
            else:
                return False, ''  # exit 0 — skip semantic scan

    # 3. Semantic patterns in output
    text = _bash_output(result)
    if text:
        m = _BASH_FAILURE_RE.search(text)
        if m:
            start = m.start()
            snippet = text[start:start + 400].strip()
            return True, snippet[:500]

    return False, ''


def extract_tool_capture(tool: str, tool_input: dict, result: dict) -> dict:
    """
    Extract relevant data from tool execution.

    Returns capture dict ready for buffering.
    """
    capture = {
        "tool": tool,
        "timestamp": int(time.time())
    }

    # Tool-specific extraction
    if tool == 'edit':
        capture['type'] = 'file_edit'
        capture['file'] = tool_input.get('file_path')
        capture['success'] = result.get('type') != 'tool_error'

    elif tool == 'write':
        capture['type'] = 'file_write'
        capture['file'] = tool_input.get('file_path')
        capture['success'] = result.get('type') != 'tool_error'

    elif tool == 'read':
        capture['type'] = 'file_read'
        capture['file'] = tool_input.get('file_path')
        capture['success'] = True

    elif tool == 'bash':
        capture['type'] = 'command'
        capture['command'] = tool_input.get('command', '')[:200]
        is_failure, error_snippet = _detect_bash_failure(result)
        capture['success'] = not is_failure
        if is_failure and error_snippet:
            capture['error'] = error_snippet

    elif tool == 'grep':
        capture['type'] = 'search'
        capture['pattern'] = tool_input.get('pattern', '')
        capture['success'] = True

    else:
        # Generic capture
        capture['type'] = 'generic'
        capture['success'] = result.get('type') != 'tool_error'

    return capture


def buffer_capture(project_id: str, capture: dict) -> int:
    """
    Buffer capture to session inbox. Returns current capture count.
    """
    inbox_dir = Path(__file__).resolve().parent.parent / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    inbox_file = inbox_dir / f"{project_id}_captures.jsonl"

    try:
        with open(inbox_file, 'a') as f:
            f.write(json.dumps(capture) + '\n')
        # Count lines efficiently
        count = sum(1 for _ in open(inbox_file))
        logger.debug(f"Buffered capture: {capture['type']} - {capture['tool']} ({count} total)")
        return count
    except Exception as e:
        logger.warning(f"Failed to buffer capture: {e}")
        return 0


def flush_episode_if_due(project_id: str, capture_count: int, plugin_root: Path) -> None:
    """
    If capture_count has hit the flush threshold, write an episode to the
    graph DB immediately and truncate the inbox — same logic as stop.py but
    without the self-note (that's reserved for true session end).

    Strict-native mode skips the Python episode/persona/patterns/semantics
    pipeline. Per the carve-outs, write_failures and write_goals would still
    run on the Python sidecar at end-of-session via stop.py; mid-session we
    intentionally defer all sidecar writes to Stop to keep this hook fast.
    """
    try:
        cfg_path = plugin_root / "config.json"
        threshold = 10
        if cfg_path.exists():
            threshold = json.loads(cfg_path.read_text()).get("a2a", {}).get("mid_session_flush_threshold", 10)

        if capture_count < threshold or capture_count % threshold != 0:
            return

        sys.path.insert(0, str(plugin_root / "mcp_server"))

        if _STRICT_NATIVE:
            # Skip Python pipeline entirely — Rust will pick everything up at
            # session end (or via the per-prompt flush in stop.flush_pending_captures).
            logger.debug(
                f"Mid-session flush skipped (strict-native mode) at {capture_count} captures"
            )
            return

        from stop import drain_session_inbox, write_episode, write_failures, write_persona, write_patterns, write_semantics

        session_data = drain_session_inbox(project_id)
        if session_data["tool_captures"]:
            store, episode_data = write_episode(project_id, session_data)
            write_failures(store, project_id, session_data)
            write_persona(store, project_id, episode_data)
            write_patterns(store, project_id)
            write_semantics(store, project_id)
            logger.info(f"Mid-session flush: all node types written at {capture_count} captures")

    except Exception as e:
        logger.warning(f"Mid-session flush failed (non-fatal): {e}")


def _buffer_traj_step(project_id: str, tool: str, capture: dict) -> None:
    """
    Buffer a lightweight trajectory step record for the native DB.
    Written to {project_id}_traj_steps.jsonl; flushed to ainl_native.db at session end.
    """
    try:
        inbox_dir = Path(__file__).resolve().parent.parent / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        step_file = inbox_dir / f"{project_id}_traj_steps.jsonl"
        step = {
            "step_id": str(uuid.uuid4()),
            "timestamp_ms": int(time.time() * 1000),
            "adapter": tool,
            "operation": capture.get("type", "run"),
            "success": capture.get("success", True),
            "error": capture.get("error"),
            "duration_ms": 0,
        }
        with open(step_file, "a") as f:
            f.write(json.dumps(step) + "\n")
    except Exception as e:
        logger.debug(f"traj step buffer failed (non-fatal): {e}")


def main():
    """Main hook entry point"""
    try:
        from shared.stdin import read_stdin_json
        input_data = read_stdin_json(hook_name="post_tool_use")

        # Claude Code PostToolUse payload: tool_name / tool_input / tool_result (top-level)
        tool_name = input_data.get('tool_name', '')
        tool_input = input_data.get('tool_input', {}) or {}
        tool_result = input_data.get('tool_result', {}) or {}

        # Use cwd from payload — hooks cd to plugin root so Path.cwd() is wrong
        cwd = Path(input_data.get('cwd', str(Path.cwd())))
        project_id = get_project_id(cwd)

        # Canonicalize tool name
        canonical_tool = canonicalize_tool(tool_name)

        logger.debug(f"Processing tool: {tool_name} → {canonical_tool}")

        # Extract capture
        capture = extract_tool_capture(canonical_tool, tool_input, tool_result)

        # Add project context
        capture['project_id'] = project_id

        # Buffer for consolidation, then flush if threshold reached
        plugin_root = Path(__file__).parent.parent
        count = buffer_capture(project_id, capture)
        flush_episode_if_due(project_id, count, plugin_root)

        # Buffer native trajectory step (persisted at session end)
        if _NATIVE_OK:
            _buffer_traj_step(project_id, canonical_tool, capture)

        # Log event
        log_event("post_tool_use", {
            "tool": canonical_tool,
            "project_id": project_id,
            "success": capture.get('success', False),
            "type": capture.get('type')
        })

        # No output needed for this hook
        print(json.dumps({}), file=sys.stdout)

    except Exception as e:
        # Fail gracefully
        log_error("post_tool_use_error", e, {
            "tool": tool_name if 'tool_name' in locals() else None
        })
        print(json.dumps({}), file=sys.stdout)

    finally:
        # Always exit 0
        sys.exit(0)


if __name__ == "__main__":
    main()
