#!/usr/bin/env python3
"""
PreCompact Hook - Compression Preparation

Prepares compression state before context compaction.
Logs compression metadata and saves session state.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))

from shared.project_id import get_project_id
from shared.logger import log_event, get_logger

logger = get_logger("pre_compact")


def main():
    try:
        input_data = json.load(sys.stdin)
        project_id = get_project_id()

        # Log pre-compact event with message info
        messages = input_data.get('messages', [])
        message_count = len(messages)

        # Estimate token count (rough estimate: 4 chars per token)
        total_chars = sum(len(str(msg.get('content', ''))) for msg in messages)
        estimated_tokens = total_chars // 4

        log_event("pre_compact", {
            "project_id": project_id,
            "message_count": message_count,
            "estimated_tokens": estimated_tokens
        })

        logger.info(f"PreCompact: {message_count} messages, ~{estimated_tokens} tokens")

        # Check if compression is enabled
        try:
            from config import get_config
            config = get_config()

            if config.is_compression_enabled():
                logger.info("Compression enabled - will be applied during compaction")

                # Log compression mode for tracking
                mode = config.get_compression_mode()
                logger.debug(f"Compression mode: {mode}")
        except Exception as config_err:
            logger.debug(f"Could not load compression config: {config_err}")

        # Return empty response (no modifications to compaction)
        print(json.dumps({}), file=sys.stdout)

    except Exception as e:
        logger.error(f"PreCompact error: {e}")
        print(json.dumps({}), file=sys.stdout)
    finally:
        sys.exit(0)


if __name__ == "__main__":
    main()
