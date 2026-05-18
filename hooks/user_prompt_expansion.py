#!/usr/bin/env python3
"""
UserPromptExpansion Hook — pass-through.

This hook fires only for slash-command expansions, not general user prompts.
Prompt compression for general messages is handled by user_prompt_submit.py
(UserPromptSubmit), which is the correct hook for that purpose.

The previous version tried to compress prompts here and output {"prompt": ...},
but "prompt" is not a valid output field for UserPromptExpansion — only
hookSpecificOutput.additionalContext and decision/reason are documented.
The output was silently discarded every time. Compression now lives solely
in user_prompt_submit.py where it actually works.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from shared.logger import get_logger

logger = get_logger("user_prompt_expansion")


def main():
    """Hook entry point — no-op pass-through."""
    try:
        from shared.stdin import read_stdin_json
        read_stdin_json(hook_name="user_prompt_expansion")
        # Nothing to inject for slash-command expansions at this time.
        print(json.dumps({}), file=sys.stdout)
    except Exception as e:
        logger.debug(f"user_prompt_expansion error (non-fatal): {e}")
        print(json.dumps({}), file=sys.stdout)
    finally:
        sys.exit(0)


if __name__ == "__main__":
    main()
