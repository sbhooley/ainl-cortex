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

from shared.project_id import get_project_id, GLOBAL_PROJECT_ID
from shared.logger import log_event, log_error, get_logger
from shared.a2a_inbox import read_inbox, clear_inbox
from shared.a2a_log import append_log
from shared.a2a_graph import store_message_node, query_thread_history

logger = get_logger("user_prompt_submit")


def format_memory_brief(context: dict, project_id: str, compress: bool = False) -> tuple:
    """
    Format memory context into compact text brief.

    Max ~800 tokens to preserve Claude Code context budget.

    Returns: (brief_text, compression_metrics, pipeline_stats)
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
    pipeline_stats = None

    # Apply unified compression pipeline if enabled
    if compress:
        try:
            # Import here to avoid circular dependency
            sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))
            from compression_pipeline import get_compression_pipeline

            pipeline = get_compression_pipeline()
            result = pipeline.compress_memory_context(brief, project_id)

            brief = result.compressed_text

            if result.compression_metrics:
                compression_metrics = {
                    "mode": result.mode_used.value,
                    "mode_source": result.mode_source,
                    "original_tokens": result.compression_metrics.original_tokens,
                    "compressed_tokens": result.compression_metrics.compressed_tokens,
                    "tokens_saved": result.compression_metrics.tokens_saved,
                    "savings_pct": result.compression_metrics.savings_ratio_pct
                }

                # Add quality score if available
                if result.preservation_score:
                    compression_metrics["quality_score"] = result.preservation_score.overall_score
                    compression_metrics["key_term_retention"] = result.preservation_score.key_term_retention

                logger.info(
                    f"Compressed memory context: {result.compression_metrics.original_tokens} → "
                    f"{result.compression_metrics.compressed_tokens} tokens "
                    f"({result.compression_metrics.savings_ratio_pct:.1f}% savings, "
                    f"mode: {result.mode_used.value}, source: {result.mode_source})"
                )

                # Log quality warnings if any
                if result.warnings:
                    for warning in result.warnings:
                        logger.warning(warning)

        except Exception as e:
            logger.warning(f"Compression pipeline failed, using original: {e}")

    # Fallback truncation if still over budget
    max_chars = 800 * 4
    if len(brief) > max_chars:
        brief = brief[:max_chars] + "\n\n[... truncated for context budget]"
        logger.warning(f"Memory brief truncated to {max_chars} chars")

    return brief, compression_metrics, pipeline_stats


def recall_context(project_id: str, prompt: str) -> dict:
    """
    Recall context from graph memory database.

    Directly accesses the SQLite database to retrieve relevant memory nodes.
    """
    try:
        # Import graph store components
        sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))
        from graph_store import SQLiteGraphStore
        from retrieval import MemoryRetrieval, RetrievalContext

        # Get database path
        memory_dir = Path.home() / ".claude" / "projects" / project_id / "graph_memory"
        db_path = memory_dir / "ainl_memory.db"

        # Check if database exists
        if not db_path.exists():
            logger.debug(f"No memory database found at {db_path}")
            return {
                'recent_episodes': [],
                'relevant_facts': [],
                'applicable_patterns': [],
                'known_failures': [],
                'persona_traits': []
            }

        # Initialize store and retrieval
        store = SQLiteGraphStore(db_path)
        retrieval = MemoryRetrieval(store)

        # Create retrieval context
        context = RetrievalContext(
            project_id=project_id,
            current_task=prompt[:200] if prompt else None,
            files_mentioned=[]
        )

        # Retrieve memory context
        memory_context = retrieval.compile_memory_context(context, max_nodes=20)

        logger.info(f"Recalled memory context: {sum(len(v) for v in memory_context.values() if isinstance(v, list))} nodes")

        return memory_context

    except Exception as e:
        logger.warning(f"Failed to recall context: {e}")
        # Return empty context on error to avoid breaking
        return {
            'recent_episodes': [],
            'relevant_facts': [],
            'applicable_patterns': [],
            'known_failures': [],
            'persona_traits': []
        }


def compress_user_prompt(prompt: str, project_id: str, config) -> tuple:
    """
    Compress user prompt using compression pipeline.

    Returns: (compressed_prompt, compression_metrics)
    """
    try:
        # Skip if prompt is too short
        min_tokens = config.get_min_tokens_for_compression()
        estimated_tokens = len(prompt) // 4 + 1

        if estimated_tokens < min_tokens:
            logger.debug(f"Skipping compression: prompt too short ({estimated_tokens} tokens < {min_tokens} min)")
            return prompt, None

        # Import compression pipeline
        sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))
        from compression_pipeline import get_compression_pipeline

        pipeline = get_compression_pipeline()
        result = pipeline.compress_user_prompt(prompt, project_id)

        compressed_prompt = result.compressed_text

        compression_metrics = None
        if result.compression_metrics:
            compression_metrics = {
                "mode": result.mode_used.value,
                "mode_source": result.mode_source,
                "original_tokens": result.compression_metrics.original_tokens,
                "compressed_tokens": result.compression_metrics.compressed_tokens,
                "tokens_saved": result.compression_metrics.tokens_saved,
                "savings_pct": result.compression_metrics.savings_ratio_pct
            }

            # Add quality scores
            if result.preservation_score:
                compression_metrics["quality_score"] = result.preservation_score.overall_score
                compression_metrics["key_term_retention"] = result.preservation_score.key_term_retention

            logger.info(
                f"⚡ Compressed user prompt: {result.compression_metrics.original_tokens} → "
                f"{result.compression_metrics.compressed_tokens} tokens "
                f"({result.compression_metrics.savings_ratio_pct:.1f}% savings, "
                f"mode: {result.mode_used.value}, source: {result.mode_source})"
            )

            # Log quality warnings
            if result.warnings:
                for warning in result.warnings:
                    logger.warning(f"Prompt compression: {warning}")

        return compressed_prompt, compression_metrics

    except Exception as e:
        logger.warning(f"User prompt compression failed, using original: {e}")
        return prompt, None


def main():
    """Main hook entry point"""
    try:
        # Read input from stdin
        input_data = json.load(sys.stdin)
        prompt = input_data.get('prompt', '')

        # Use cwd from payload — hooks cd to plugin root so Path.cwd() is wrong
        cwd = Path(input_data.get('cwd', str(Path.cwd())))
        project_id = get_project_id(cwd)

        logger.info(f"Processing prompt for project {project_id}")

        # Load config for compression settings
        sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))
        from config import get_config
        config = get_config()

        # Compress user prompt if enabled
        prompt_compression_metrics = None
        if config.should_compress_user_prompt():
            logger.info("User prompt compression enabled")
            compressed_prompt, prompt_compression_metrics = compress_user_prompt(prompt, project_id, config)
            # Use compressed prompt for memory recall and further processing
            prompt_for_recall = compressed_prompt
        else:
            logger.debug("User prompt compression disabled")
            prompt_for_recall = prompt

        # Recall context from graph memory (using potentially compressed prompt)
        context = recall_context(project_id, prompt_for_recall)

        # Check if memory context compression should be used
        use_memory_compression = config.should_compress_memory_context()

        # Format compact brief (with unified compression pipeline)
        brief, memory_compression_metrics, pipeline_stats = format_memory_brief(
            context,
            project_id,
            compress=use_memory_compression
        )

        # ── A2A inbox injection ───────────────────────────────────────────────
        plugin_root = Path(__file__).parent.parent
        a2a_blocks = {"critical": [], "normal": [], "low": []}
        a2a_cfg = {}
        try:
            import json as _json
            a2a_cfg = _json.loads((plugin_root / "config.json").read_text()).get("a2a", {})
        except Exception:
            pass

        if a2a_cfg.get("enabled", True):
            inbox_dir = plugin_root / "a2a" / "inbox"
            db_path = Path.home() / ".claude" / "projects" / GLOBAL_PROJECT_ID / "graph_memory" / "ainl_memory.db"
            messages = read_inbox(
                inbox_dir,
                max_messages=a2a_cfg.get("inbox_max_messages", 50),
                max_age_seconds=a2a_cfg.get("inbox_max_age_seconds", 86400),
                max_message_chars=a2a_cfg.get("inbox_max_message_chars", 2000),
            )

            if messages:
                seen_threads = {}
                for msg in messages:
                    urgency = msg.get("urgency", "normal")
                    from_agent = msg.get("from_agent", "unknown")
                    thread_id = msg.get("thread_id")
                    msg_text = msg.get("message", "")
                    msg_type = msg.get("type", "message")

                    # Graph write
                    store_message_node(
                        db_path, GLOBAL_PROJECT_ID,
                        "inbound", from_agent, "claude-code",
                        thread_id, urgency, msg_text,
                    )
                    # Log write
                    append_log(
                        plugin_root, "IN", from_agent, "claude-code",
                        thread_id or "none", urgency, msg_text[:120],
                    )

                    # Thread history (recall once per unique thread)
                    thread_context = ""
                    if thread_id and thread_id not in seen_threads:
                        history = query_thread_history(db_path, GLOBAL_PROJECT_ID, thread_id, n=a2a_cfg.get("thread_recall_n", 5))
                        if history:
                            lines = [f"  Prior context with {from_agent} (thread {thread_id[:8]}):"]
                            for h in history[:3]:
                                lines.append(f"    - {h.data.get('fact', '')[:100]}")
                            thread_context = "\n".join(lines)
                            seen_threads[thread_id] = thread_context

                    type_label = "TASK RESULT" if msg_type == "task_result" else "MESSAGE"
                    entry = f"[A2A {type_label} from {from_agent}]"
                    if thread_id:
                        entry += f" (thread:{thread_id[:8]})"
                    entry += f"\n{msg_text}"
                    if thread_context:
                        entry += f"\n{thread_context}"

                    tier = urgency if urgency in a2a_blocks else "normal"
                    a2a_blocks[tier].append(entry)

                clear_inbox(inbox_dir)
                logger.info(f"Injected {len(messages)} A2A messages (critical:{len(a2a_blocks['critical'])} normal:{len(a2a_blocks['normal'])} low:{len(a2a_blocks['low'])})")

        # ── Assemble system message ───────────────────────────────────────────
        system_parts = []

        if a2a_blocks["critical"]:
            block = "\n\n".join(a2a_blocks["critical"])
            system_parts.append(f"━━━ CRITICAL A2A MESSAGES ━━━\n{block}\n━━━ END CRITICAL ━━━")

        if brief.strip() and len(brief) > len("## Relevant Graph Memory\n\n"):
            system_parts.append(brief)

        other_a2a = a2a_blocks["normal"] or a2a_blocks["low"]
        if other_a2a:
            block = "\n\n".join(a2a_blocks["normal"] + a2a_blocks["low"])
            system_parts.append(f"── A2A Inbox ──\n{block}\n── End Inbox ──")

        # Prepare result
        result = {}

        # If prompt was compressed, use the compressed version
        if prompt_compression_metrics and prompt_compression_metrics['tokens_saved'] > 0:
            result["prompt"] = compressed_prompt
            logger.info(f"✅ User prompt compressed: {prompt_compression_metrics['tokens_saved']} tokens saved ({prompt_compression_metrics['savings_pct']:.0f}%)")

        # Inject system message if we have anything
        assembled = "\n\n".join(system_parts)
        if assembled.strip():
            result["systemMessage"] = assembled
            logger.info(f"Injected {len(assembled)} chars of context")

        if memory_compression_metrics and memory_compression_metrics.get('tokens_saved', 0) > 0:
            logger.info(f"⚡ eco: {memory_compression_metrics['savings_pct']:.0f}% savings on memory context")

        # Log event with both compression metrics
        log_event("user_prompt_submit", {
            "project_id": project_id,
            "prompt_length": len(prompt),
            "brief_length": len(brief),
            "injected": bool(result),
            "prompt_compression": prompt_compression_metrics,
            "memory_compression": memory_compression_metrics
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
