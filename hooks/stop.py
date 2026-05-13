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
from typing import Optional

try:
    import ainl_native as _ainl_native
    _NATIVE_OK = True
except ImportError:
    _ainl_native = None
    _NATIVE_OK = False

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))

from shared.project_id import get_project_id, get_project_info
from shared.logger import log_event, log_error, get_logger
from shared.a2a_inbox import write_self_note

logger = get_logger("stop")


def drain_session_inbox(project_id: str) -> dict:
    """Drain buffered captures from inbox, return aggregated session data."""
    inbox_dir = Path(__file__).resolve().parent.parent / "inbox"
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
    from graph_store import get_graph_store
    from node_types import GraphNode, NodeType

    task_summary = create_episode_summary(session_data)
    outcome = "partial" if session_data["had_errors"] else "success"
    now = int(time.time())

    db_path = Path.home() / ".claude" / "projects" / project_id / "graph_memory" / "ainl_memory.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    store = get_graph_store(db_path)

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

    # Enrich episode with native semantic tags if available
    native_tags: list = []
    if _NATIVE_OK:
        try:
            tags = _ainl_native.tag_turn(task_summary, None, session_data.get("tools_used", []))
            native_tags = [{"namespace": t["namespace"], "value": t["value"]} for t in tags[:10]]
        except Exception as _e:
            logger.debug("tag_turn failed (non-fatal): %s", _e)

    node = GraphNode(
        id=str(uuid.uuid4()),
        node_type=NodeType.EPISODE,
        project_id=project_id,
        agent_id="claude-code",
        created_at=now,
        updated_at=now,
        confidence=1.0,
        data=episode_data,
        metadata={"native_tags": native_tags} if native_tags else {},
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
            file=capture.get("file"),
            command=capture.get("command", "")[:200] if capture.get("command") else None,
        )
        store.write_node(node)
        count += 1

    if count:
        logger.info(f"Wrote {count} failure node(s)")
    return count


def link_resolutions(store, project_id: str, episode_data: dict) -> int:
    """
    Retrospectively link open failure nodes to the episode that resolved them.

    After a successful episode, check all unresolved failures for this project.
    If the episode touched the same file(s) or used the same tool as the failure,
    assume the episode resolved it: write a RESOLVES edge and update the failure
    node's resolution/resolved_at fields.

    Returns the number of failures linked.
    """
    if episode_data.get("outcome") not in ("success",):
        return 0

    from node_types import create_edge, EdgeType
    import time as _time

    episode_files = set(episode_data.get("files_touched", []))
    episode_tools = set(episode_data.get("tool_calls", []))
    episode_id = episode_data.get("turn_id", "")
    episode_task = episode_data.get("task_description", "")
    now = int(_time.time())

    unresolved = store.get_unresolved_failures(project_id)
    linked = 0

    for failure in unresolved:
        fail_file = failure.data.get("file") or ""
        fail_tool = failure.data.get("tool") or ""

        file_match = bool(fail_file and episode_files and fail_file in episode_files)
        tool_match = bool(fail_tool and fail_tool in episode_tools)

        if not (file_match or tool_match):
            continue

        # Update the failure node with resolution info
        store.update_node_data(failure.id, {
            "resolution": f"Resolved by: {episode_task[:150]}",
            "resolution_turn_id": episode_id,
            "resolved_at": now,
        })

        # Write RESOLVES edge (episode → failure) — need the episode node ID
        # The episode was just written; query it by turn_id
        try:
            recent = store.query_episodes_since(now - 10, limit=5, project_id=project_id)
            ep_node_id = None
            for ep in recent:
                if ep.data.get("turn_id") == episode_id:
                    ep_node_id = ep.id
                    break

            if ep_node_id:
                edge = create_edge(
                    from_node=ep_node_id,
                    to_node=failure.id,
                    edge_type=EdgeType.RESOLVES,
                    project_id=project_id,
                    metadata={"matched_on": "file" if file_match else "tool"}
                )
                store.write_edge(edge)
        except Exception as edge_err:
            logger.debug(f"Could not write RESOLVES edge: {edge_err}")

        linked += 1

    if linked:
        logger.info(f"Linked {linked} failure resolution(s) to episode {episode_id[:8]}")
    return linked


def write_persona(store, project_id: str, episode_data: dict) -> int:
    """Evolve persona traits from episode signals (Python fallback path).

    Native persona evolution is handled by finalize_session in ainl_native.
    """
    from node_types import create_persona_node

    # ── Python fallback ─────────────────────────────────────────────────────
    try:
        from persona_engine import PersonaEvolutionEngine
    except ImportError:
        return 0

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
        logger.info(f"Python persona: wrote {count} trait(s): {[t['trait_name'] for t in traits]}")
    return count


def write_semantics(store, project_id: str) -> int:
    """
    Mine semantic facts from accumulated episode and failure history.

    Patterns detected across multiple sessions:
      - Files touched in 3+ episodes          → "frequently modified core file"
      - Tools used in 50%+ episodes           → "consistently used tool"
      - Error type in 3+ failures             → "recurring failure pattern"
      - Tool in 3+ failures                   → "error-prone tool"
      - File in 2+ failures                   → "failure-associated file"
      - Sessions majority partial/error       → "project has persistent complexity"

    Skips facts that are already represented in existing semantic nodes
    (prefix-based fingerprint dedup — prevents re-writing the same fact
    every session).
    """
    from collections import Counter
    from node_types import create_semantic_node, NodeType
    # Counter is also used in prompt mining section below (imported as _Counter there)

    MIN_EP = 3    # minimum episode occurrences for a file/tool fact
    MIN_FAIL = 2  # minimum failure occurrences for a failure fact

    # ── Fetch history ─────────────────────────────────────────────────────────
    try:
        episode_nodes = store.query_by_type(NodeType.EPISODE, project_id, limit=100)
        failure_nodes = store.query_by_type(NodeType.FAILURE, project_id, limit=100)
        semantic_nodes = store.query_by_type(NodeType.SEMANTIC, project_id, limit=500)
    except Exception:
        return 0

    n_ep = len(episode_nodes)
    if n_ep < MIN_EP:
        return 0  # Not enough history yet

    # ── Build frequency tables ────────────────────────────────────────────────
    file_counts: Counter = Counter()
    tool_counts: Counter = Counter()
    partial_count = 0

    for ep in episode_nodes:
        d = ep.data if isinstance(ep.data, dict) else {}
        for f in d.get("files_touched", []):
            file_counts[Path(f).name] += 1
        for t in d.get("tool_calls", []):
            tool_counts[t] += 1
        if d.get("outcome") in ("partial", "failure"):
            partial_count += 1

    fail_type_counts: Counter = Counter()
    fail_tool_counts: Counter = Counter()
    fail_file_counts: Counter = Counter()

    for fail in failure_nodes:
        d = fail.data if isinstance(fail.data, dict) else {}
        if d.get("error_type"):
            fail_type_counts[d["error_type"]] += 1
        if d.get("tool"):
            fail_tool_counts[d["tool"]] += 1
        # file is an optional field in FailureData
        if d.get("file"):
            fail_file_counts[Path(d["file"]).name] += 1

    # ── Build candidate facts ─────────────────────────────────────────────────
    candidates: list = []  # list of (fact_str, confidence)

    for fname, count in file_counts.most_common(15):
        if count >= MIN_EP:
            conf = min(count / n_ep, 1.0)
            candidates.append((
                f"File '{fname}' is a frequently modified core file (seen in {count}/{n_ep} sessions)",
                conf,
            ))

    for tool, count in tool_counts.most_common(10):
        ratio = count / n_ep
        if ratio >= 0.5 and count >= MIN_EP:
            candidates.append((
                f"Tool '{tool}' is consistently used across this project ({count} uses in {n_ep} sessions)",
                min(ratio, 1.0),
            ))

    for err_type, count in fail_type_counts.most_common(10):
        if count >= MIN_FAIL and err_type:
            conf = min(count / max(n_ep, 1), 1.0)
            candidates.append((
                f"Recurring failure pattern: '{err_type}' has occurred {count} time(s)",
                conf,
            ))

    for tool, count in fail_tool_counts.most_common(10):
        if count >= MIN_FAIL and tool:
            conf = min(count / max(n_ep, 1), 1.0)
            candidates.append((
                f"Tool '{tool}' is error-prone in this project ({count} failure(s) recorded)",
                conf,
            ))

    for fname, count in fail_file_counts.most_common(10):
        if count >= MIN_FAIL:
            conf = min(count / max(n_ep, 1), 1.0)
            candidates.append((
                f"File '{fname}' is associated with repeated failures ({count} time(s))",
                conf,
            ))

    if partial_count / n_ep >= 0.6:
        candidates.append((
            f"This project consistently produces complex multi-step outcomes "
            f"({partial_count}/{n_ep} sessions ended partial/error)",
            partial_count / n_ep,
        ))

    # ── Prompt history mining ─────────────────────────────────────────────────
    import re as _re
    hist_file = (
        Path(__file__).resolve().parent.parent
        / "inbox" / f"{project_id}_prompts.jsonl"
    )
    if hist_file.exists():
        try:
            prompt_records = []
            for line in hist_file.read_text().strip().splitlines():
                try:
                    prompt_records.append(json.loads(line))
                except Exception:
                    pass

            n_p = len(prompt_records)
            if n_p >= 5:
                _Counter = Counter

                STOPWORDS = {
                    'which', 'there', 'their', 'about', 'would', 'could', 'should',
                    'make', 'into', 'also', 'just', 'like', 'then', 'than', 'some',
                    'your', 'been', 'were', 'they', 'them', 'does', 'dont', 'cant',
                    'that', 'this', 'with', 'from', 'have', 'what', 'when', 'will',
                    'plugin', 'claude', 'using', 'right', 'going', 'need', 'want',
                    'think', 'know', 'understand', 'something', 'anything', 'everything',
                }

                # File names mentioned in prompts
                pfile_counts: Counter = _Counter()
                for rec in prompt_records:
                    for f in rec.get("files", []):
                        pfile_counts[Path(f).name] += 1

                # Technical identifiers (snake_case names)
                tech_counts: Counter = _Counter()
                for rec in prompt_records:
                    for t in rec.get("tech_ids", []):
                        if len(t) >= 6 and t not in STOPWORDS:
                            tech_counts[t] += 1

                # Action verbs — what the user most often requests
                action_counts: Counter = _Counter()
                for rec in prompt_records:
                    if rec.get("action"):
                        action_counts[rec["action"]] += 1

                # Promote prompt-derived facts
                for fname, count in pfile_counts.most_common(10):
                    if count >= MIN_EP:
                        conf = min(count / n_p, 1.0)
                        candidates.append((
                            f"File '{fname}' is frequently referenced in user prompts "
                            f"({count}/{n_p} prompts)",
                            conf,
                        ))

                for tid, count in tech_counts.most_common(8):
                    if count >= MIN_EP:
                        conf = min(count / n_p, 1.0)
                        candidates.append((
                            f"'{tid}' is a frequently discussed technical concept "
                            f"({count}/{n_p} prompts)",
                            conf,
                        ))

                top_actions = [a for a, _ in action_counts.most_common(3) if action_counts[a] >= MIN_EP]
                if top_actions:
                    candidates.append((
                        f"Most requested operations in this project: "
                        f"{', '.join(top_actions)} "
                        f"(across {n_p} prompts)",
                        0.8,
                    ))
        except Exception as e:
            logger.debug(f"Prompt history mining failed (non-fatal): {e}")

    # ── Dedup against existing semantic nodes ─────────────────────────────────
    # Use first 50 chars of existing facts as fingerprints
    existing_fingerprints = {
        n.data.get("fact", "")[:50]
        for n in semantic_nodes
        if isinstance(n.data, dict)
    }

    count = 0
    for fact, confidence in candidates:
        fingerprint = fact[:50]
        if any(fingerprint[:30] in fp for fp in existing_fingerprints):
            continue  # Already have a similar fact
        node = create_semantic_node(
            project_id=project_id,
            fact=fact,
            confidence=round(confidence, 3),
        )
        store.write_node(node)
        existing_fingerprints.add(fingerprint)
        count += 1

    if count:
        logger.info(f"Wrote {count} semantic fact(s) from cross-session pattern mining")
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


def write_goals(store, project_id: str, episode_data: Optional[dict] = None) -> int:
    """
    Update active goals from the latest episode and, at session end,
    auto-infer new goals from episode clusters if none exist yet.

    Returns number of goal nodes created or updated.
    """
    try:
        from goal_tracker import GoalTracker
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_server"))
        from goal_tracker import GoalTracker

    tracker = GoalTracker(store, project_id)
    updated = 0

    # Auto-update active goals with the latest episode
    if episode_data:
        try:
            updated += tracker.auto_update_from_episode(episode_data)
        except Exception as e:
            logger.debug(f"Goal auto-update failed: {e}")

    # If there are no active goals at all, try to infer some from recent episodes
    try:
        active = store.query_goals(project_id, status="active", limit=1)
        if not active:
            recent_eps = store.query_episodes_since(since=0, limit=20, project_id=project_id)
            if recent_eps:
                new_ids = tracker.infer_goals_from_episodes(recent_eps)
                updated += len(new_ids)
    except Exception as e:
        logger.debug(f"Goal inference failed: {e}")

    return updated


def flush_pending_captures(project_id: str) -> int:
    """
    Flush any buffered captures to the graph DB right now.
    Called at the start of each UserPromptSubmit so every completed turn is
    persisted even if the session ends abruptly before Stop fires.
    Returns number of captures flushed (0 = nothing pending).
    """
    inbox_dir = Path(__file__).resolve().parent.parent / "inbox"
    inbox_file = inbox_dir / f"{project_id}_captures.jsonl"
    if not inbox_file.exists():
        return 0
    try:
        count = sum(1 for _ in open(inbox_file))
    except Exception:
        return 0
    if count == 0:
        return 0
    try:
        session_data = drain_session_inbox(project_id)
        if session_data["tool_captures"]:
            store, episode_data = write_episode(project_id, session_data)
            write_failures(store, project_id, session_data)
            if episode_data:
                if not _NATIVE_OK:
                    write_persona(store, project_id, episode_data)
                link_resolutions(store, project_id, episode_data)
            write_patterns(store, project_id)
            write_semantics(store, project_id)
            write_goals(store, project_id, episode_data)
            if _NATIVE_OK:
                try:
                    native_db_path = str(Path.home() / ".claude" / "projects" / project_id / "graph_memory" / "ainl_native.db")
                    inbox_dir = Path(__file__).resolve().parent.parent / "inbox"
                    step_file = str(inbox_dir / f"{project_id}_traj_steps.jsonl")
                    task_summary = create_episode_summary(session_data)
                    outcome = "partial" if session_data["had_errors"] else "success"
                    session_json = json.dumps({
                        "tool_calls": session_data.get("tools_used", []),
                        "files_touched": session_data.get("files_touched", []),
                        "had_errors": session_data.get("had_errors", False),
                        "task_summary": task_summary,
                        "outcome": outcome,
                        "capture_count": count,
                    })
                    _ainl_native.finalize_session(native_db_path, project_id, session_json, step_file)
                except Exception as _ne:
                    logger.debug(f"Per-prompt native finalize_session failed (non-fatal): {_ne}")
            logger.info(f"Per-prompt flush: wrote all node types for {count} captures")
        return count
    except Exception as e:
        logger.warning(f"Per-prompt flush failed (non-fatal): {e}")
        return 0



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
            # Native mode: persona is handled by finalize_session (Rust) — skip Python path
            if episode_data and not _NATIVE_OK:
                write_persona(store, project_id, episode_data)
        except Exception as e:
            logger.warning(f"Persona write failed: {e}")

        try:
            if episode_data:
                link_resolutions(store, project_id, episode_data)
        except Exception as e:
            logger.warning(f"Resolution linking failed: {e}")

        try:
            write_patterns(store, project_id)
        except Exception as e:
            logger.warning(f"Pattern write failed: {e}")

        try:
            write_semantics(store, project_id)
        except Exception as e:
            logger.warning(f"Semantic write failed: {e}")

        try:
            write_goals(store, project_id, episode_data)
        except Exception as e:
            logger.warning(f"Goal write failed: {e}")

    # Drain compression events and update auto-tune profile
    try:
        _inbox_dir = Path(__file__).resolve().parent.parent / "inbox"
        _evt_file = _inbox_dir / f"{project_id}_compression_events.jsonl"
        if _evt_file.exists():
            events = [json.loads(l) for l in _evt_file.read_text().strip().splitlines() if l.strip()]
            if events:
                _profile_db = Path.home() / ".claude" / "projects" / project_id / "graph_memory" / "ainl_memory.db"
                _profile_db.parent.mkdir(parents=True, exist_ok=True)
                from compression_profiles import CompressionProfileStore
                _cps = CompressionProfileStore(_profile_db)
                _had_errors = session_data.get("had_errors", False)
                for _evt in events:
                    _cps.record_compression_result(
                        project_id=project_id,
                        mode=_evt["mode"],
                        token_savings_pct=_evt["savings_pct"],
                        user_corrected=_had_errors,
                    )
                _evt_file.unlink()
                logger.debug(f"Drained {len(events)} compression event(s) for auto-tune")
    except Exception as _ce:
        logger.debug(f"Compression event drain failed (non-fatal): {_ce}")

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

    # Consolidated native finalization: trajectory + persona + procedure learning + anchored summary
    if _NATIVE_OK:
        try:
            native_db_path = str(Path.home() / ".claude" / "projects" / project_id / "graph_memory" / "ainl_native.db")
            inbox_dir = Path(__file__).resolve().parent.parent / "inbox"
            step_file = str(inbox_dir / f"{project_id}_traj_steps.jsonl")
            session_json = json.dumps({
                "tool_calls": session_data.get("tools_used", []),
                "files_touched": session_data.get("files_touched", []),
                "had_errors": session_data.get("had_errors", False),
                "task_summary": task_summary,
                "outcome": outcome,
                "capture_count": len(session_data.get("tool_captures", [])),
            })
            result = _ainl_native.finalize_session(native_db_path, project_id, session_json, step_file)
            logger.info(
                f"Native finalize_session: episode={result.get('episode_id', '?')[:8]}, "
                f"traj_steps={result.get('trajectory_steps', 0)}, "
                f"procedures={result.get('procedures_promoted', 0)}, "
                f"summary={result.get('summary_saved', False)}"
            )
        except Exception as e:
            logger.debug(f"Native finalize_session failed (non-fatal): {e}")

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
