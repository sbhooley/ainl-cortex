#!/usr/bin/env python3
"""
PostToolUse Hook - Capture Execution

Captures tool outcomes and buffers for MCP server consolidation.
Follows AINL pattern: lightweight capture, async consolidation.
"""

import sys
import json
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).parent))

from shared.project_id import get_project_id
from shared.logger import log_event, log_error, get_logger

logger = get_logger("post_tool_use")


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
        capture['command'] = tool_input.get('command', '')[:200]  # Limit length
        capture['success'] = result.get('type') != 'tool_error'

        # Extract error text if present
        if not capture['success']:
            error_text = result.get('text', '') or result.get('error', '')
            if error_text:
                capture['error'] = error_text[:500]

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
    inbox_dir = Path.home() / ".claude" / "plugins" / "ainl-graph-memory" / "inbox"
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
    """
    try:
        cfg_path = plugin_root / "config.json"
        threshold = 10
        if cfg_path.exists():
            threshold = json.loads(cfg_path.read_text()).get("a2a", {}).get("mid_session_flush_threshold", 10)

        if capture_count < threshold or capture_count % threshold != 0:
            return

        sys.path.insert(0, str(plugin_root / "mcp_server"))
        from stop import drain_session_inbox, write_episode, write_failures, write_persona, write_patterns

        session_data = drain_session_inbox(project_id)
        if session_data["tool_captures"]:
            store, episode_data = write_episode(project_id, session_data)
            write_failures(store, project_id, session_data)
            write_persona(store, project_id, episode_data)
            write_patterns(store, project_id)
            logger.info(f"Mid-session flush: all nodes written at {capture_count} captures")

    except Exception as e:
        logger.warning(f"Mid-session flush failed (non-fatal): {e}")


def main():
    """Main hook entry point"""
    try:
        # Read input from stdin
        input_data = json.load(sys.stdin)

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
