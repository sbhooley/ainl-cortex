#!/usr/bin/env python3
"""
PostCompact Hook — Update anchored summary after context compaction.

After compaction, update the anchored summary to reflect the compacted state.
This ensures the next session start injection shows the correct "in progress"
context rather than stale prior-session data.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))

from shared.project_id import get_project_id
from shared.logger import log_event, get_logger

logger = get_logger("post_compact")

try:
    import ainl_native as _ainl_native
    _NATIVE_OK = True
except ImportError:
    _ainl_native = None
    _NATIVE_OK = False


def main():
    try:
        from shared.stdin import read_stdin_json
        input_data = read_stdin_json(hook_name="post_compact")
        project_id = get_project_id()

        messages_before = input_data.get('messagesBefore', 0)
        messages_after = input_data.get('messagesAfter', 0)
        messages_removed = messages_before - messages_after
        estimated_tokens_saved = messages_removed * 200

        log_event("post_compact", {
            "project_id": project_id,
            "messages_before": messages_before,
            "messages_after": messages_after,
            "messages_removed": messages_removed,
            "estimated_tokens_saved": estimated_tokens_saved,
        })
        logger.info(f"PostCompact: {messages_removed} messages removed, ~{estimated_tokens_saved} tokens saved")

        # Update anchored summary to reflect post-compaction state
        if _NATIVE_OK:
            try:
                db_path = Path.home() / ".claude" / "projects" / project_id / "graph_memory"
                db_path.mkdir(parents=True, exist_ok=True)
                native_db = str(db_path / "ainl_native.db")
                store = _ainl_native.AinlNativeStore.open(native_db)

                # Fetch existing summary to preserve task context
                prior_raw = store.fetch_anchored_summary("claude-code")
                prior_summary = "session compacted"
                prior_ts = int(time.time())
                if prior_raw:
                    try:
                        p = json.loads(prior_raw)
                        prior_summary = p.get("task_summary", prior_summary)
                        prior_ts = p.get("session_ts", prior_ts)
                    except Exception:
                        pass

                payload = json.dumps({
                    "schema_version": 1,
                    "task_summary": prior_summary,
                    "outcome": "in_progress",
                    "post_compaction": True,
                    "messages_after_compaction": messages_after,
                    "tokens_saved_by_compaction": estimated_tokens_saved,
                    "session_ts": prior_ts,
                    "compacted_at": int(time.time()),
                    "project_id": project_id,
                }, separators=(",", ":"))

                node_id = store.upsert_anchored_summary("claude-code", payload)
                logger.info(f"PostCompact anchored summary updated: {node_id}")
            except Exception as e:
                logger.debug(f"PostCompact summary update failed (non-fatal): {e}")

        print(json.dumps({}), file=sys.stdout)

    except Exception as e:
        logger.error(f"PostCompact error: {e}")
        print(json.dumps({}), file=sys.stdout)
    finally:
        sys.exit(0)


if __name__ == "__main__":
    main()
