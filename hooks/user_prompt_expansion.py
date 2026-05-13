#!/usr/bin/env python3
"""
UserPromptExpansion Hook - User Prompt Compression

Compresses user prompts to save tokens while preserving meaning.
Uses the unified compression pipeline with semantic preservation.
"""

import sys
import json
from pathlib import Path

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.project_id import get_project_id
from shared.logger import log_event, log_error, get_logger

logger = get_logger("user_prompt_expansion")


def compress_user_prompt(prompt: str, project_id: str) -> tuple:
    """
    Compress user prompt using the unified compression pipeline.

    Returns: (compressed_prompt, compression_metrics)
    """
    try:
        from mcp_server.compression_pipeline import get_compression_pipeline
        from mcp_server.config import get_config

        config = get_config()

        # Check if user prompt compression is enabled
        if not config.should_compress_user_prompt():
            logger.debug("User prompt compression disabled")
            return prompt, None

        # Check minimum token threshold
        min_tokens = config.get_min_tokens_for_compression()
        estimated_tokens = len(prompt) // 4  # Rough estimate

        if estimated_tokens < min_tokens:
            logger.debug(f"Prompt too short ({estimated_tokens} tokens < {min_tokens} min)")
            return prompt, None

        # Get compression pipeline
        pipeline = get_compression_pipeline()

        # Compress the prompt
        result = pipeline.compress_user_prompt(prompt, project_id)

        if result.compression_metrics:
            metrics = {
                "mode": result.mode_used.value,
                "mode_source": result.mode_source,
                "original_tokens": result.compression_metrics.original_tokens,
                "compressed_tokens": result.compression_metrics.compressed_tokens,
                "tokens_saved": result.compression_metrics.tokens_saved,
                "savings_pct": result.compression_metrics.savings_ratio_pct
            }

            if result.preservation_score:
                metrics["quality_score"] = result.preservation_score.overall_score
                metrics["key_term_retention"] = result.preservation_score.key_term_retention

            logger.info(
                f"Compressed user prompt: {result.compression_metrics.original_tokens} → "
                f"{result.compression_metrics.compressed_tokens} tokens "
                f"({result.compression_metrics.savings_ratio_pct:.1f}% savings)"
            )

            # Log quality warnings if any
            if result.warnings:
                for warning in result.warnings:
                    logger.warning(warning)

            return result.compressed_text, metrics

        return prompt, None

    except Exception as e:
        logger.warning(f"Compression failed, using original prompt: {e}")
        return prompt, None


def main():
    """Main hook entry point"""
    try:
        from shared.stdin import read_stdin_json
        input_data = read_stdin_json(hook_name="user_prompt_expansion")
        prompt = input_data.get('prompt', '')

        if not prompt:
            logger.debug("Empty prompt, skipping compression")
            print(json.dumps({}), file=sys.stdout)
            sys.exit(0)

        # Get project ID
        cwd = Path.cwd()
        project_id = get_project_id(cwd)

        logger.info(f"Processing prompt compression for project {project_id}")

        # Compress the prompt
        compressed_prompt, compression_metrics = compress_user_prompt(prompt, project_id)

        # Prepare result
        result = {}

        # If compression happened, return the compressed prompt
        if compressed_prompt != prompt and compression_metrics:
            result["prompt"] = compressed_prompt
            logger.info(f"⚡ eco: {compression_metrics['savings_pct']:.0f}% token savings on user prompt")
        else:
            logger.debug("No compression applied")

        # Log event
        log_event("user_prompt_expansion", {
            "project_id": project_id,
            "original_length": len(prompt),
            "compressed_length": len(compressed_prompt),
            "compression": compression_metrics
        })

        # Output result as JSON
        print(json.dumps(result), file=sys.stdout)

    except Exception as e:
        # Fail gracefully - never break Claude Code
        log_error("user_prompt_expansion_error", e, {
            "input": input_data if 'input_data' in locals() else None
        })
        print(json.dumps({}), file=sys.stdout)

    finally:
        # Always exit 0
        sys.exit(0)


if __name__ == "__main__":
    main()
