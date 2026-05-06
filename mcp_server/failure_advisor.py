"""
AINL Failure Advisor

At the start of each user turn, analyses the incoming prompt against the
project's failure history and injects proactive warnings when a strong match
is found.  Each warning includes the original error AND the resolution (if one
has been linked via the RESOLVES/FIXED_BY edge graph).

Design goals:
- Zero false positives preferred over recall: threshold is conservative (0.3)
- Max 3 warnings per prompt so the context injection stays concise
- Resolution text is sourced from the linked fix episode, not free-text
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

# Patterns that indicate an action is about to be taken on a file or command
_FILE_PAT = re.compile(r'\b[\w./\\-]+\.(?:py|ts|tsx|js|json|yaml|yml|sql|sh|md|txt|cfg|toml|env)\b')
_CMD_PAT = re.compile(r'\b(?:git|npm|pip|python|pytest|docker|bash|sh|make|cargo|go)\b')
_TECH_PAT = re.compile(r'\b[a-z][a-z0-9]*(?:_[a-z0-9]+){1,}\b')  # snake_case identifiers


@dataclass
class FailureWarning:
    """A single actionable warning derived from failure history."""
    error_type: str
    error_summary: str       # Trimmed error_message
    resolution: str          # How it was fixed (may be empty if unresolved)
    confidence: float        # 0.0–1.0 match confidence
    matched_on: str          # 'file', 'command', 'semantic', or 'tool'
    failure_node_id: str
    file: Optional[str] = None


class FailureAdvisor:
    """
    Analyse an incoming prompt against stored failure nodes and return ranked
    warnings that Claude should surface before taking action.
    """

    # Conservative threshold — only warn when match is fairly strong
    MIN_CONFIDENCE = 0.3
    MAX_WARNINGS = 3

    def __init__(self, store, project_id: str):
        self.store = store
        self.project_id = project_id

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyse_prompt(self, prompt: str) -> List[FailureWarning]:
        """
        Return up to MAX_WARNINGS relevant failure warnings for this prompt.
        Returns an empty list when there is nothing noteworthy.
        """
        try:
            failures = self.store.get_unresolved_failures(self.project_id, limit=100)
            if not failures:
                return []

            context = self._extract_prompt_context(prompt)
            scored = []

            for node in failures:
                score, matched_on = self._score_failure(node.data, context)
                if score >= self.MIN_CONFIDENCE:
                    resolution = self._get_resolution(node)
                    warning = FailureWarning(
                        error_type=node.data.get('error_type', 'error'),
                        error_summary=node.data.get('error_message', '')[:120],
                        resolution=resolution,
                        confidence=score,
                        matched_on=matched_on,
                        failure_node_id=node.id,
                        file=node.data.get('file'),
                    )
                    scored.append((warning, score))

            scored.sort(key=lambda x: x[1], reverse=True)
            return [w for w, _ in scored[:self.MAX_WARNINGS]]
        except Exception as e:
            logger.debug(f"FailureAdvisor.analyse_prompt failed (non-fatal): {e}")
            return []

    def format_warnings(self, warnings: List[FailureWarning]) -> str:
        """
        Format warnings as a compact markdown block for context injection.
        """
        if not warnings:
            return ""

        lines = ["**⚠ Failure History — Relevant Cautions:**"]
        for w in warnings:
            loc = f" in `{w.file}`" if w.file else ""
            lines.append(f"\n- **{w.error_type}**{loc} (confidence {w.confidence:.0%})")
            lines.append(f"  Error: {w.error_summary}")
            if w.resolution:
                lines.append(f"  Fix applied previously: {w.resolution}")
            else:
                lines.append(f"  Status: unresolved — proceed with care")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _extract_prompt_context(self, prompt: str) -> Dict[str, Any]:
        return {
            "files": set(_FILE_PAT.findall(prompt.lower())),
            "commands": set(_CMD_PAT.findall(prompt.lower())),
            "tech_ids": set(_TECH_PAT.findall(prompt.lower())),
            "text": prompt.lower(),
        }

    def _score_failure(
        self, failure_data: Dict[str, Any], context: Dict[str, Any]
    ) -> tuple[float, str]:
        """
        Return (score, matched_on) where score is in [0, 1].
        Uses three independent signals that are combined without exceeding 1.0.
        """
        score = 0.0
        matched_on = "semantic"

        # Signal 1: file match — check full path AND basename (strong signal)
        fail_file = (failure_data.get('file') or '').lower()
        fail_basename = fail_file.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
        ctx_files = context["files"]
        ctx_basenames = {f.rsplit('/', 1)[-1].rsplit('\\', 1)[-1] for f in ctx_files}
        if fail_file and (fail_file in ctx_files or fail_basename in ctx_basenames):
            score += 0.55
            matched_on = "file"

        # Signal 2: command / tool match (medium signal)
        fail_cmd = (failure_data.get('command') or '').lower()
        fail_tool = (failure_data.get('tool') or '').lower()
        if fail_tool in context["commands"] or any(c in fail_cmd for c in context["commands"] if c):
            score += 0.3
            matched_on = matched_on if matched_on == "file" else "command"

        # Signal 3: TF-IDF-like keyword overlap (soft signal)
        if score < 0.3:
            error_tokens = set(re.findall(r'[a-z0-9_]+', (
                (failure_data.get('error_message') or '') + ' ' +
                (failure_data.get('error_type') or '')
            ).lower()))
            overlap = error_tokens & context["tech_ids"]
            if overlap:
                overlap_score = min(0.4, len(overlap) * 0.15)
                score += overlap_score

        return min(score, 1.0), matched_on

    def _get_resolution(self, failure_node) -> str:
        """
        Look up the resolution for a failure node.
        Priority: 1) failure.data.resolution field  2) RESOLVES edge → episode task
        """
        resolution = failure_node.data.get('resolution') or ''
        if resolution:
            return resolution[:200]

        # Follow RESOLVES edge (episode → failure)
        try:
            from node_types import EdgeType
            edges = self.store.get_edges_to(failure_node.id, EdgeType.RESOLVES)
            if edges:
                fix_episode = self.store.get_node(edges[0].from_node)
                if fix_episode:
                    task = fix_episode.data.get('task_description', '')
                    return task[:200]
        except Exception:
            pass

        return ''
