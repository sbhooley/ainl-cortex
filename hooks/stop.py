#!/usr/bin/env python3
"""
Stop Hook - Session Finalization

Finalizes session, writes episode node to SQLite graph store.
"""

import sys
import json
import uuid
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))

from shared.project_id import get_project_id, get_project_info
from shared.logger import log_event, log_error, get_logger
from shared.a2a_inbox import write_self_note

logger = get_logger("stop")


def drain_session_inbox(project_id: str) -> dict:
    """Drain buffered captures from inbox, return aggregated session data."""
    inbox_dir = Path.home() / ".claude" / "plugins" / "ainl-graph-memory" / "inbox"
    inbox_file = inbox_dir / f"{project_id}_captures.jsonl"

    session_data = {
        "tool_captures": [],
        "files_touched": set(),
        "tools_used": set(),
        "had_errors": False
    }

    if not inbox_file.exists():
        logger.debug("No inbox file found")
        return session_data

    try:
        with open(inbox_file, 'r') as f:
            for line in f:
                if line.strip():
                    capture = json.loads(line)
                    session_data["tool_captures"].append(capture)
                    session_data["tools_used"].add(capture.get("tool", "unknown"))
                    file = capture.get("file")
                    if file:
                        session_data["files_touched"].add(file)
                    if not capture.get("success", True):
                        session_data["had_errors"] = True

        inbox_file.unlink()
        logger.info(f"Drained {len(session_data['tool_captures'])} captures")

    except Exception as e:
        logger.warning(f"Failed to drain inbox: {e}")

    session_data["files_touched"] = list(session_data["files_touched"])
    session_data["tools_used"] = list(session_data["tools_used"])
    return session_data


def create_episode_summary(session_data: dict) -> str:
    """Generate human-readable task description from session data."""
    tools = [t for t in session_data["tools_used"] if t]
    files = session_data["files_touched"]

    parts = []
    if tools:
        parts.append(f"tools: {', '.join(sorted(tools)[:5])}")
    if files:
        parts.append(f"files: {', '.join(Path(f).name for f in files[:3])}")

    summary = "Session — " + "; ".join(parts) if parts else "Session"
    if session_data["had_errors"]:
        summary += " (with errors)"
    return summary


def write_episode(project_id: str, session_data: dict):
    """
    Write episode node. Returns (store, episode_data_dict) for downstream writers.
    """
    from graph_store import SQLiteGraphStore
    from node_types import GraphNode, NodeType

    task_summary = create_episode_summary(session_data)
    outcome = "partial" if session_data["had_errors"] else "success"
    now = int(time.time())

    db_path = Path.home() / ".claude" / "projects" / project_id / "graph_memory" / "ainl_memory.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    store = SQLiteGraphStore(db_path)

    episode_data = {
        "turn_id": str(uuid.uuid4()),
        "task_description": task_summary,
        "tool_calls": session_data["tools_used"],
        "files_touched": session_data["files_touched"],
        "outcome": outcome,
        "duration_ms": 0,
        "git_commit": None,
        "test_results": None,
        "session_id": None,
        "error_message": None,
    }

    node = GraphNode(
        id=str(uuid.uuid4()),
        node_type=NodeType.EPISODE,
        project_id=project_id,
        agent_id="claude-code",
        created_at=now,
        updated_at=now,
        confidence=1.0,
        data=episode_data,
        metadata={},
        embedding_text=task_summary,
    )

    store.write_node(node)
    logger.info(f"Created episode: project={project_id}, task={task_summary}, outcome={outcome}")
    return store, episode_data


def write_failures(store, project_id: str, session_data: dict) -> int:
    """Write a failure node for every errored tool capture in the session."""
    from node_types import create_failure_node

    count = 0
    for capture in session_data.get("tool_captures", []):
        if capture.get("success", True):
            continue
        node = create_failure_node(
            project_id=project_id,
            error_type=capture.get("type", "tool_error"),
            tool=capture.get("tool", "unknown"),
            error_message=capture.get("error", "")[:500],
        )
        store.write_node(node)
        count += 1

    if count:
        logger.info(f"Wrote {count} failure node(s)")
    return count


def write_persona(store, project_id: str, episode_data: dict) -> int:
    """Evolve persona traits from episode signals and write persona nodes."""
    from persona_engine import PersonaEvolutionEngine
    from node_types import create_persona_node

    engine = PersonaEvolutionEngine()
    signals = engine.extract_signals_from_episode(episode_data)
    if not signals:
        return 0

    engine.ingest_signals(signals)
    traits = engine.get_active_traits(min_strength=0.1)

    count = 0
    for trait in traits:
        node = create_persona_node(
            project_id=project_id,
            trait_name=trait["trait_name"],
            strength=trait["strength"],
            learned_from=[episode_data.get("turn_id", "")],
        )
        store.write_node(node)
        count += 1

    if count:
        logger.info(f"Wrote {count} persona trait(s): {[t['trait_name'] for t in traits]}")
    return count


def write_patterns(store, project_id: str) -> int:
    """
    Scan recent successful episodes for repeated tool sequences.
    Promote any new patterns that meet the fitness threshold.
    """
    from extractor import PatternExtractor
    from node_types import create_procedural_node, NodeType

    # Fetch recent episodes (need at least 2 to detect repetition)
    try:
        recent_nodes = store.query_episodes_since(since=0, limit=100, project_id=project_id)
    except Exception:
        return 0

    if len(recent_nodes) < 2:
        return 0

    # Convert GraphNode objects to the dict shape PatternExtractor expects
    episodes = [{"data": n.data} for n in recent_nodes]

    # Fetch existing procedural patterns to avoid re-promoting
    existing_patterns = []
    try:
        all_nodes = store.search_fts("", project_id, limit=200)
        existing_patterns = [
            {"data": n.data}
            for n in all_nodes
            if n.node_type == NodeType.PROCEDURAL
        ]
    except Exception:
        pass

    extractor = PatternExtractor()
    new_patterns = extractor.extract_patterns(episodes, existing_patterns)

    count = 0
    for pat in new_patterns:
        node = create_procedural_node(
            project_id=project_id,
            pattern_name=pat["pattern_name"],
            trigger=pat["trigger"],
            tool_sequence=pat["tool_sequence"],
            success_count=pat["success_count"],
            evidence_ids=pat["evidence_ids"],
        )
        store.write_node(node)
        count += 1

    if count:
        logger.info(f"Promoted {count} new procedural pattern(s)")
    return count


def finalize_session(project_id: str, session_data: dict, plugin_root: Path) -> None:
    """Write all node types, self-note (if substantial), and log structured event."""
    task_summary = create_episode_summary(session_data)
    outcome = "partial" if session_data["had_errors"] else "success"

    store = None
    episode_data = None
    try:
        store, episode_data = write_episode(project_id, session_data)
    except Exception as e:
        logger.warning(f"Episode write failed: {e}")

    if store:
        try:
            write_failures(store, project_id, session_data)
        except Exception as e:
            logger.warning(f"Failure nodes write failed: {e}")

        try:
            if episode_data:
                write_persona(store, project_id, episode_data)
        except Exception as e:
            logger.warning(f"Persona write failed: {e}")

        try:
            write_patterns(store, project_id)
        except Exception as e:
            logger.warning(f"Pattern write failed: {e}")

    # Write self-note if session was substantial (helps resume next session)
    try:
        import json as _json
        cfg_path = plugin_root / "config.json"
        threshold = 5
        if cfg_path.exists():
            threshold = _json.loads(cfg_path.read_text()).get("a2a", {}).get("self_note_threshold", 5)

        capture_count = len(session_data.get("tool_captures", []))
        if capture_count >= threshold:
            tools = session_data.get("tools_used", [])
            files = session_data.get("files_touched", [])
            message = (
                f"Prior session summary: {task_summary}. "
                f"Outcome: {outcome}. "
                f"Tools: {', '.join(sorted(tools)[:8])}. "
                f"Files: {', '.join(Path(f).name for f in files[:5])}."
            )
            note_id = write_self_note(
                plugin_root,
                message=message,
                context=f"Session had {capture_count} tool calls.",
                urgency="critical",
                tool_count=capture_count,
            )
            logger.info(f"Self-note written: {note_id} ({capture_count} captures)")
    except Exception as e:
        logger.warning(f"Self-note write failed: {e}")

    log_event("session_finalized", {
        "project_id": project_id,
        "task_summary": task_summary,
        "tools_used": session_data["tools_used"],
        "files_touched": session_data["files_touched"],
        "outcome": outcome,
        "capture_count": len(session_data["tool_captures"])
    })


def main():
    """Main hook entry point"""
    try:
        try:
            input_data = json.load(sys.stdin)
        except json.JSONDecodeError:
            input_data = {}

        # Use cwd from payload — hooks run with cd to plugin root
        cwd = Path(input_data.get('cwd', str(Path.cwd())))
        project_info = get_project_info(cwd)
        project_id = project_info["project_id"]
        plugin_root = Path(__file__).parent.parent

        logger.info(f"Finalizing session for project {project_id}")

        session_data = drain_session_inbox(project_id)

        if session_data["tool_captures"]:
            finalize_session(project_id, session_data, plugin_root)
        else:
            logger.debug("No session data to finalize")

        print(json.dumps({}), file=sys.stdout)

    except Exception as e:
        log_error("stop_error", e, {
            "project_id": project_id if 'project_id' in locals() else None
        })
        print(json.dumps({}), file=sys.stdout)

    finally:
        sys.exit(0)


if __name__ == "__main__":
    main()
