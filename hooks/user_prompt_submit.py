#!/usr/bin/env python3
"""
UserPromptSubmit Hook - Context Injection

Injects relevant graph memory into context before Claude processes the prompt.
Follows AINL retrieval pattern: compact, ranked, project-scoped.
"""

import sys
import json
from pathlib import Path

# Add shared module to path
sys.path.insert(0, str(Path(__file__).parent))

from shared.project_id import get_project_id
from shared.logger import log_event, log_error, get_logger

logger = get_logger("user_prompt_submit")


def format_memory_brief(context: dict, compress: bool = False, compression_mode: str = "balanced") -> tuple:
    """
    Format memory context into compact text brief.

    Max ~800 tokens to preserve Claude Code context budget.

    Returns: (brief_text, compression_metrics)
    """
    lines = ["## Relevant Graph Memory", ""]

    # Recent episodes
    episodes = context.get('recent_episodes', [])
    if episodes:
        lines.append("**Recent Work:**")
        for ep in episodes[:3]:
            import time
            timestamp = time.strftime('%Y-%m-%d', time.localtime(ep['created_at']))
            task = ep['data']['task_description'][:60]
            outcome = ep['data']['outcome']
            lines.append(f"- [{timestamp}] {task} → {outcome}")
        lines.append("")

    # Relevant facts
    facts = context.get('relevant_facts', [])
    if facts:
        lines.append("**Known Facts:**")
        for fact in facts[:5]:
            fact_text = fact['data']['fact'][:80]
            confidence = fact['confidence']
            lines.append(f"- {fact_text} (conf: {confidence:.2f})")
        lines.append("")

    # Applicable patterns
    patterns = context.get('applicable_patterns', [])
    if patterns:
        lines.append("**Reusable Patterns:**")
        for pat in patterns[:2]:
            name = pat['data']['pattern_name']
            sequence = ' → '.join(pat['data']['tool_sequence'][:4])
            fitness = pat['data']['fitness']
            lines.append(f"- \"{name}\": {sequence} (fitness: {fitness:.2f})")
        lines.append("")

    # Known failures
    failures = context.get('known_failures', [])
    if failures:
        lines.append("**Known Issues:**")
        for fail in failures[:3]:
            file = fail['data'].get('file', 'unknown')
            line_num = fail['data'].get('line', '?')
            msg = fail['data'].get('error_message', '')[:60]
            lines.append(f"- {file}:{line_num}: {msg}")
        lines.append("")

    # Persona traits
    traits = context.get('persona_traits', [])
    if traits:
        trait_strs = []
        for trait in traits[:3]:
            name = trait['data']['trait_name']
            strength = trait['data']['strength']
            trait_strs.append(f"{name} ({strength:.2f})")

        if trait_strs:
            lines.append(f"**Project Style:** {', '.join(trait_strs)}")
            lines.append("")

    brief = "\n".join(lines)

    compression_metrics = None

    # Apply AINL compression if enabled
    if compress:
        try:
            # Import here to avoid circular dependency
            sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))
            from compression import compress_text

            compressed, metrics = compress_text(brief, mode=compression_mode, emit_metrics=True)

            if metrics and metrics.tokens_saved > 0:
                brief = compressed
                compression_metrics = {
                    "mode": compression_mode,
                    "original_tokens": metrics.original_tokens,
                    "compressed_tokens": metrics.compressed_tokens,
                    "tokens_saved": metrics.tokens_saved,
                    "savings_pct": metrics.savings_ratio_pct
                }
                logger.info(
                    f"Compressed memory context: {metrics.original_tokens} → "
                    f"{metrics.compressed_tokens} tokens ({metrics.savings_ratio_pct:.1f}% savings)"
                )
        except Exception as e:
            logger.warning(f"Compression failed, using original: {e}")

    # Fallback truncation if still over budget
    max_chars = 800 * 4
    if len(brief) > max_chars:
        brief = brief[:max_chars] + "\n\n[... truncated for context budget]"
        logger.warning(f"Memory brief truncated to {max_chars} chars")

    return brief, compression_metrics


def recall_context(project_id: str, prompt: str) -> dict:
    """
    Call MCP server to recall context.

    In production, this would use MCP client library.
    For now, we return empty context gracefully.
    """
    # TODO: Implement MCP client call when MCP SDK is integrated
    # For now, return empty context to avoid breaking
    logger.debug(f"Would recall context for project {project_id}, prompt: {prompt[:50]}...")

    return {
        'recent_episodes': [],
        'relevant_facts': [],
        'applicable_patterns': [],
        'known_failures': [],
        'persona_traits': []
    }


def main():
    """Main hook entry point"""
    try:
        # Read input from stdin
        input_data = json.load(sys.stdin)
        prompt = input_data.get('prompt', '')

        # Get project ID
        cwd = Path.cwd()
        project_id = get_project_id(cwd)

        logger.info(f"Processing prompt for project {project_id}")

        # Recall context from graph memory
        context = recall_context(project_id, prompt)

        # Check if compression should be used
        # TODO: Load from config file when MCP integration is complete
        use_compression = True  # Default to enabled
        compression_mode = "balanced"  # Default mode

        # Format compact brief (with optional compression)
        brief, compression_metrics = format_memory_brief(
            context,
            compress=use_compression,
            compression_mode=compression_mode
        )

        # Prepare result
        result = {}

        # Only inject if we have meaningful content
        if brief.strip() and len(brief) > len("## Relevant Graph Memory\n\n"):
            result["systemMessage"] = brief
            logger.info(f"Injected {len(brief)} chars of memory context")

            # Add compression badge if compression was used
            if compression_metrics and compression_metrics['tokens_saved'] > 0:
                savings_pct = compression_metrics['savings_pct']
                logger.info(f"⚡ eco: {savings_pct:.0f}% token savings on memory context")
        else:
            logger.debug("No memory context to inject")

        # Log event
        log_event("user_prompt_submit", {
            "project_id": project_id,
            "prompt_length": len(prompt),
            "brief_length": len(brief),
            "injected": bool(result),
            "compression": compression_metrics
        })

        # Output result as JSON
        print(json.dumps(result), file=sys.stdout)

    except Exception as e:
        # Fail gracefully - never break Claude Code
        log_error("user_prompt_submit_error", e, {
            "input": input_data if 'input_data' in locals() else None
        })
        print(json.dumps({}), file=sys.stdout)

    finally:
        # Always exit 0
        sys.exit(0)


if __name__ == "__main__":
    main()
