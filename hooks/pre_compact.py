#!/usr/bin/env python3
"""
PreCompact Hook — Safety flush before context compaction.

PreCompact cannot modify what the compaction summary contains, but it CAN:
  1. Flush all buffered captures to the native graph DB (zero data loss at compaction)
  2. Snapshot the current session state into the anchored summary (so the
     next session start has context that reflects work done *before* compaction,
     not just the last session-end state)

Both actions are fire-and-forget; failures are non-fatal.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))

from shared.project_id import get_project_id
from shared.logger import log_event, get_logger

logger = get_logger("pre_compact")

try:
    import ainl_native as _ainl_native
    _NATIVE_OK = True
except ImportError:
    _ainl_native = None
    _NATIVE_OK = False


def _flush_and_snapshot(project_id: str, message_count: int, estimated_tokens: int) -> None:
    """Flush pending captures and update anchored summary before compaction."""
    # ── 1. Flush all buffered session captures ────────────────────────────────
    try:
        from stop import flush_pending_captures
        flushed = flush_pending_captures(project_id)
        if flushed:
            logger.info(f"PreCompact safety flush: {flushed} captures committed before compaction")
    except Exception as e:
        logger.debug(f"PreCompact flush failed (non-fatal): {e}")

    # ── 2. Snapshot anchored summary with current session state ───────────────
    if not _NATIVE_OK:
        return
    try:
        inbox_dir = Path(__file__).resolve().parent.parent / "inbox"
        captures_file = inbox_dir / f"{project_id}_captures.jsonl"
        capture_count = 0
        if captures_file.exists():
            try:
                capture_count = sum(1 for _ in open(captures_file))
            except Exception:
                pass

        db_path = Path.home() / ".claude" / "projects" / project_id / "graph_memory"
        db_path.mkdir(parents=True, exist_ok=True)
        native_db = str(db_path / "ainl_native.db")
        store = _ainl_native.AinlNativeStore.open(native_db)

        # Fetch prior summary to preserve task context
        prior_raw = store.fetch_anchored_summary("claude-code")
        prior_summary = "ongoing"
        if prior_raw:
            try:
                prior_summary = json.loads(prior_raw).get("task_summary", "ongoing")
            except Exception:
                pass

        payload = json.dumps({
            "schema_version": 1,
            "task_summary": prior_summary,
            "outcome": "in_progress",
            "compaction_snapshot": True,
            "context_messages_before": message_count,
            "estimated_tokens": estimated_tokens,
            "capture_count": capture_count,
            "session_ts": int(time.time()),
            "project_id": project_id,
        }, separators=(",", ":"))

        node_id = store.upsert_anchored_summary("claude-code", payload)
        logger.info(f"PreCompact anchored snapshot saved: {node_id}")
    except Exception as e:
        logger.debug(f"PreCompact snapshot failed (non-fatal): {e}")


def main():
    try:
        from shared.stdin import read_stdin_json
        input_data = read_stdin_json(hook_name="pre_compact")
        project_id = get_project_id()

        messages = input_data.get('messages', [])
        message_count = len(messages)
        total_chars = sum(len(str(msg.get('content', ''))) for msg in messages)
        estimated_tokens = total_chars // 4

        log_event("pre_compact", {
            "project_id": project_id,
            "message_count": message_count,
            "estimated_tokens": estimated_tokens,
            "trigger": input_data.get("trigger", "auto"),
        })
        logger.info(f"PreCompact: {message_count} messages, ~{estimated_tokens} tokens — flushing + snapshotting")

        _flush_and_snapshot(project_id, message_count, estimated_tokens)

        print(json.dumps({}), file=sys.stdout)

    except Exception as e:
        logger.error(f"PreCompact error: {e}")
        print(json.dumps({}), file=sys.stdout)
    finally:
        sys.exit(0)


if __name__ == "__main__":
    main()
