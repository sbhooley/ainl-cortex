"""
AINL Goal Tracker

Persists multi-session intent as GOAL nodes in the graph DB.

Goals live across sessions — they are the "why" behind clusters of episodes.
They can be:
  - Explicitly set by Claude via MCP tool (memory_set_goal)
  - Auto-inferred from episode clusters at session end
  - Auto-updated when new episodes match an active goal

Auto-inference algorithm:
  1. Cluster recent episodes by shared files/tools (sliding window)
  2. Name clusters by dominant action verb + file basename
  3. Propose a GOAL node for any cluster of 3+ episodes that isn't already
     covered by an existing active goal (checked via TF-IDF overlap)

Auto-update algorithm (called after each episode write):
  1. Score the new episode against every active goal via keyword overlap
  2. If score > threshold, add the episode to goal.contributing_episodes
     and append a timestamped progress note
  3. Mark goal "completed" if it has a completion_criteria and the latest
     episode's task_description contains keywords from it
"""

import re
import logging
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Verbs that indicate meaningful progress vs. maintenance
_ACTION_VERBS = {
    'add', 'build', 'create', 'design', 'implement', 'integrate',
    'fix', 'debug', 'resolve', 'repair', 'refactor', 'clean',
    'update', 'upgrade', 'migrate', 'port', 'convert',
    'test', 'validate', 'verify', 'document',
}
_VERB_PAT = re.compile(r'\b(' + '|'.join(_ACTION_VERBS) + r')\b', re.IGNORECASE)
_TECH_PAT = re.compile(r'\b[a-z][a-z0-9]*(?:_[a-z0-9]+){1,}\b')
_FILE_BASE = re.compile(r'\b([\w-]+)\.\w{2,6}\b')


def _dominant_verb(text: str) -> str:
    matches = _VERB_PAT.findall(text)
    if not matches:
        return "work on"
    return Counter(m.lower() for m in matches).most_common(1)[0][0]


def _keywords(text: str) -> set:
    tokens = set(re.findall(r'[a-z0-9_]+', text.lower()))
    stop = {'the', 'a', 'an', 'and', 'or', 'to', 'of', 'in', 'is', 'it',
            'for', 'on', 'with', 'this', 'that', 'be', 'are', 'was', 'were'}
    return tokens - stop


def _keyword_overlap(a: str, b: str) -> float:
    ka, kb = _keywords(a), _keywords(b)
    if not ka or not kb:
        return 0.0
    return len(ka & kb) / len(ka | kb)


class GoalTracker:
    """
    Manages GOAL nodes for a project.
    """

    # How many episodes must share context before auto-inferring a goal
    MIN_CLUSTER_SIZE = 3
    # How similar an episode must be to an active goal to link to it
    LINK_THRESHOLD = 0.15
    # Max goals to inject into context
    MAX_CONTEXT_GOALS = 5

    def __init__(self, store, project_id: str):
        self.store = store
        self.project_id = project_id

    # ------------------------------------------------------------------
    # Explicit goal management (called via MCP tools)
    # ------------------------------------------------------------------

    def create_goal(
        self,
        title: str,
        description: str,
        completion_criteria: Optional[str] = None,
        tags: Optional[List[str]] = None,
        inferred: bool = False,
    ) -> str:
        """Create and persist a new GOAL node. Returns the new node ID."""
        try:
            from node_types import create_goal_node
        except ImportError:
            import sys
            sys.path.insert(0, str(Path(__file__).parent))
            from node_types import create_goal_node

        node = create_goal_node(
            project_id=self.project_id,
            title=title,
            description=description,
            status="active",
            inferred=inferred,
            completion_criteria=completion_criteria or "",
            tags=tags or [],
        )
        self.store.write_node(node)
        logger.info(f"Created goal '{title}' ({node.id[:8]})")
        return node.id

    def update_goal(
        self,
        goal_id: str,
        status: Optional[str] = None,
        progress_note: Optional[str] = None,
    ) -> bool:
        """Update status and/or append a progress note. Returns True on success."""
        node = self.store.get_node(goal_id)
        if not node or node.node_type.value != 'goal':
            return False
        patch: Dict[str, Any] = {}
        if status:
            patch['status'] = status
        if progress_note:
            notes = node.data.get('progress_notes', [])
            notes.append({'ts': int(time.time()), 'note': progress_note[:300]})
            patch['progress_notes'] = notes
        if patch:
            self.store.update_node_data(goal_id, patch)
        return True

    def complete_goal(self, goal_id: str, summary: Optional[str] = None) -> bool:
        note = summary or "Goal marked complete."
        return self.update_goal(goal_id, status="completed", progress_note=note)

    def abandon_goal(self, goal_id: str, reason: Optional[str] = None) -> bool:
        note = reason or "Goal abandoned."
        return self.update_goal(goal_id, status="abandoned", progress_note=note)

    def get_active_goals(self) -> List[Dict[str, Any]]:
        """Return active goal nodes as dicts, newest first."""
        nodes = self.store.query_goals(self.project_id, status="active", limit=self.MAX_CONTEXT_GOALS)
        return [n.to_dict() for n in nodes]

    def get_all_goals(self, include_completed: bool = False) -> List[Dict[str, Any]]:
        nodes = self.store.query_goals(self.project_id)
        if not include_completed:
            nodes = [n for n in nodes if n.data.get('status') != 'completed']
        return [n.to_dict() for n in nodes]

    # ------------------------------------------------------------------
    # Auto-update: link an episode to matching active goals
    # ------------------------------------------------------------------

    def auto_update_from_episode(self, episode_data: Dict[str, Any]) -> int:
        """
        Score `episode_data` against every active goal.  For goals where
        keyword overlap exceeds LINK_THRESHOLD:
          - Add episode turn_id to contributing_episodes (dedup)
          - Append a progress note
          - Check if completion_criteria is now met

        Returns number of goals updated.
        """
        active_nodes = self.store.query_goals(self.project_id, status="active")
        if not active_nodes:
            return 0

        episode_text = " ".join(filter(None, [
            episode_data.get("task_description", ""),
            " ".join(episode_data.get("files_touched", [])),
            " ".join(episode_data.get("tool_calls", [])),
        ]))
        episode_id = episode_data.get("turn_id", "")
        updated = 0

        for node in active_nodes:
            goal_text = f"{node.data.get('title', '')} {node.data.get('description', '')}"
            sim = _keyword_overlap(goal_text, episode_text)
            if sim < self.LINK_THRESHOLD:
                continue

            # Dedup contributing_episodes
            contrib = node.data.get('contributing_episodes', [])
            if episode_id and episode_id not in contrib:
                contrib.append(episode_id)

            patch: Dict[str, Any] = {
                'contributing_episodes': contrib,
                'last_active_session': str(int(time.time())),
            }

            # Append progress note
            notes = node.data.get('progress_notes', [])
            task = episode_data.get('task_description', '')[:120]
            outcome = episode_data.get('outcome', 'unknown')
            notes.append({'ts': int(time.time()), 'note': f"[{outcome}] {task}"})
            patch['progress_notes'] = notes

            # Check completion criteria
            criteria = (node.data.get('completion_criteria') or '').strip()
            if criteria:
                criteria_kw = _keywords(criteria)
                episode_kw = _keywords(episode_text)
                if criteria_kw and len(criteria_kw & episode_kw) / len(criteria_kw) > 0.6:
                    patch['status'] = 'completed'
                    logger.info(f"Goal '{node.data.get('title')}' auto-completed")

            self.store.update_node_data(node.id, patch)

            # Write GOAL_TRACKS edge if we have the episode node ID
            try:
                from node_types import create_edge, EdgeType
                recent = self.store.query_episodes_since(int(time.time()) - 30, limit=10, project_id=self.project_id)
                ep_node = next((e for e in recent if e.data.get('turn_id') == episode_id), None)
                if ep_node:
                    edge = create_edge(
                        from_node=node.id,
                        to_node=ep_node.id,
                        edge_type=EdgeType.GOAL_TRACKS,
                        project_id=self.project_id,
                        metadata={'similarity': round(sim, 3)},
                    )
                    self.store.write_edge(edge)
            except Exception as edge_err:
                logger.debug(f"GOAL_TRACKS edge failed: {edge_err}")

            updated += 1

        return updated

    # ------------------------------------------------------------------
    # Auto-inference: derive goals from episode clusters
    # ------------------------------------------------------------------

    def infer_goals_from_episodes(self, episodes: List[Any], dry_run: bool = False) -> List[str]:
        """
        Cluster `episodes` by shared file context and propose GOAL nodes for
        any cluster that isn't already covered by an existing active goal.

        Returns list of new goal node IDs (or proposed titles if dry_run=True).
        """
        if len(episodes) < self.MIN_CLUSTER_SIZE:
            return []

        # Build file → episode index
        file_to_eps: Dict[str, List[Any]] = defaultdict(list)
        for ep in episodes:
            for f in ep.data.get('files_touched', []):
                base = Path(f).name
                file_to_eps[base].append(ep)

        # Find files that appear in enough episodes to suggest a recurring goal
        clusters = {
            fname: eps
            for fname, eps in file_to_eps.items()
            if len(eps) >= self.MIN_CLUSTER_SIZE
        }

        if not clusters:
            return []

        # Load existing goals to avoid duplicates
        existing_goals = self.store.query_goals(self.project_id)
        existing_texts = [
            f"{g.data.get('title', '')} {g.data.get('description', '')}"
            for g in existing_goals
        ]

        created = []
        for fname, cluster_eps in clusters.items():
            # Name the goal from the dominant action verb + file base
            cluster_text = " ".join(ep.data.get('task_description', '') for ep in cluster_eps)
            verb = _dominant_verb(cluster_text)
            tech_ids = _TECH_PAT.findall(fname.replace('.', '_'))
            subject = tech_ids[0] if tech_ids else fname.rsplit('.', 1)[0]
            title = f"{verb.capitalize()} {subject}"
            description = (
                f"Auto-inferred: {len(cluster_eps)} sessions touched `{fname}`. "
                f"Recurring activity: {cluster_text[:100]}..."
            )

            # Skip if an existing goal already covers this cluster
            already_covered = any(
                _keyword_overlap(f"{title} {description}", existing)
                > 0.35
                for existing in existing_texts
            )
            if already_covered:
                continue

            if dry_run:
                created.append(title)
            else:
                goal_id = self.create_goal(
                    title=title,
                    description=description,
                    inferred=True,
                    tags=[fname, verb],
                )
                created.append(goal_id)
                existing_texts.append(f"{title} {description}")

        if created:
            logger.info(f"Auto-inferred {len(created)} goal(s): {created}")
        return created

    # ------------------------------------------------------------------
    # Context formatting
    # ------------------------------------------------------------------

    def format_goal_context(self, goals: List[Dict[str, Any]]) -> str:
        """
        Compact markdown block for injection into the system message.
        Only active goals are shown; completed/abandoned ones are excluded.
        """
        active = [g for g in goals if g.get('data', {}).get('status') == 'active']
        if not active:
            return ""

        lines = ["**Active Goals (persisted across sessions):**"]
        for g in active[:self.MAX_CONTEXT_GOALS]:
            d = g.get('data', {})
            title = d.get('title', 'Untitled')
            desc = d.get('description', '')[:100]
            criteria = d.get('completion_criteria', '')
            ep_count = len(d.get('contributing_episodes', []))
            tag = " *(inferred)*" if d.get('inferred') else ""
            lines.append(f"\n- **{title}**{tag}: {desc}")
            if criteria:
                lines.append(f"  Done when: {criteria[:80]}")
            if ep_count:
                lines.append(f"  Progress: {ep_count} session(s) contributing")

        return "\n".join(lines)
