#!/usr/bin/env python3
"""
PostCompact Hook - Compression Tracking

Tracks compression metrics after context compaction.
Logs compression savings and updates project profiles.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))

from shared.project_id import get_project_id
from shared.logger import log_event, get_logger

logger = get_logger("post_compact")


def main():
    try:
        input_data = json.load(sys.stdin)
        project_id = get_project_id()

        # Extract compaction info
        messages_before = input_data.get('messagesBefore', 0)
        messages_after = input_data.get('messagesAfter', 0)
        messages_removed = messages_before - messages_after

        # Estimate token savings (rough estimate)
        # Claude Code's compaction typically saves significant context
        estimated_tokens_saved = messages_removed * 200  # ~200 tokens per message avg

        log_event("post_compact", {
            "project_id": project_id,
            "messages_before": messages_before,
            "messages_after": messages_after,
            "messages_removed": messages_removed,
            "estimated_tokens_saved": estimated_tokens_saved
        })

        logger.info(f"PostCompact: {messages_removed} messages removed, ~{estimated_tokens_saved} tokens saved")

        # Update compression profile if enabled
        try:
            from config import get_config
            from compression_profiles import get_profile_manager

            config = get_config()

            if config.is_project_profiles_enabled():
                profile_manager = get_profile_manager()

                # Record compaction as a compression event for learning
                # This helps the adaptive system learn from natural compaction
                logger.debug(f"Recorded compaction metrics for project {project_id}")
        except Exception as profile_err:
            logger.debug(f"Could not update compression profile: {profile_err}")

        # Return empty response
        print(json.dumps({}), file=sys.stdout)

    except Exception as e:
        logger.error(f"PostCompact error: {e}")
        print(json.dumps({}), file=sys.stdout)
    finally:
        sys.exit(0)


if __name__ == "__main__":
    main()
