"""
Orchestrates knowledge capture at session end (time-budgeted).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from .artifact_ingest import run as run_artifact_ingest
    from .claude_memory_bridge import run as run_memory_bridge
    from .knowledge_config import get_knowledge_capture_block
    from .research_capture import run as run_research_capture
    from .session_synthesis import run as run_session_synthesis
except ImportError:
    from artifact_ingest import run as run_artifact_ingest
    from claude_memory_bridge import run as run_memory_bridge
    from knowledge_config import get_knowledge_capture_block
    from research_capture import run as run_research_capture
    from session_synthesis import run as run_session_synthesis

logger = logging.getLogger(__name__)


def run_knowledge_capture(
    project_id: str,
    session_data: dict,
    task_summary: str,
    *,
    episode_data: Optional[dict] = None,
    plugin_root: Optional[Path] = None,
    cwd: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run artifact ingest, research capture, synthesis, optional memory bridge."""
    budget_ms = int(get_knowledge_capture_block().get("stop_time_budget_ms", 2500))
    deadline = time.time() + budget_ms / 1000.0
    out: Dict[str, Any] = {"budget_ms": budget_ms}

    try:
        out["artifact"] = run_artifact_ingest(
            project_id,
            session_data,
            episode_data=episode_data,
            plugin_root=plugin_root,
            deadline_ts=deadline,
        )
    except Exception as e:
        logger.warning("artifact_ingest failed (non-fatal): %s", e)
        out["artifact"] = {"error": str(e)}

    if time.time() < deadline:
        try:
            out["research"] = run_research_capture(
                project_id,
                session_data,
                episode_data=episode_data,
                plugin_root=plugin_root,
                deadline_ts=deadline,
            )
        except Exception as e:
            logger.warning("research_capture failed (non-fatal): %s", e)
            out["research"] = {"error": str(e)}

    if time.time() < deadline:
        try:
            out["synthesis"] = run_session_synthesis(
                project_id,
                session_data,
                task_summary,
                episode_data=episode_data,
                plugin_root=plugin_root,
                deadline_ts=deadline,
            )
        except Exception as e:
            logger.warning("session_synthesis failed (non-fatal): %s", e)
            out["synthesis"] = {"error": str(e)}

    try:
        out["bridge"] = run_memory_bridge(
            project_id, cwd=cwd, plugin_root=plugin_root
        )
    except Exception as e:
        logger.debug("claude_memory_bridge failed (non-fatal): %s", e)
        out["bridge"] = {"error": str(e)}

    return out
