"""
AINL Failure Advisor

At the start of each user turn, analyses the incoming prompt against the
project's failure history and injects proactive warnings when a strong match
is found.  Each warning includes the original error AND the resolution (if one
has been linked via the RESOLVES/FIXED_BY edge graph).

Matching uses a three-signal hybrid:
  1. File/path exact match         — high precision (+0.55)
  2. Command/tool match            — medium precision (+0.30)
  3. TF-IDF cosine + Jaccard blend — broad semantic recall

Two thresholds prevent false positives:
  - MIN_CONFIDENCE_PRECISE (0.30): file or command signal fired
  - MIN_CONFIDENCE_SEMANTIC (0.18): semantic-only match

Design goals:
- Works for both organically-captured AND manually-stored failures
- Zero false positives preferred over recall
- Max 3 warnings per prompt so context injection stays concise
- Resolution text sourced from linked fix episode, not free-text
- All paths non-fatal: hook must never break Claude Code
"""

import re
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_FILE_PAT = re.compile(
    r'\b[\w./\\-]+\.(?:py|ts|tsx|js|json|yaml|yml|sql|sh|ainl|lang|md|txt|cfg|toml|env)\b'
)
# Expanded to include 'ainl' so AINL tool names match
_CMD_PAT = re.compile(
    r'\b(?:ainl|git|npm|pip|python|pytest|docker|bash|sh|make|cargo|go)\b'
)

# Minimum corpus size to attempt TF-IDF (requires >= 2 docs)
_TFIDF_MIN_DOCS = 2


@dataclass
class FailureWarning:
    """A single actionable warning derived from failure history."""
    error_type: str
    error_summary: str       # Trimmed error_message
    resolution: str          # How it was fixed (may be empty if unresolved)
    confidence: float        # 0.0–1.0 match confidence
    matched_on: str          # 'file', 'command', or 'semantic'
    failure_node_id: str
    file: Optional[str] = None


class FailureAdvisor:
    """
    Analyse an incoming prompt against stored failure nodes and return ranked
    warnings that Claude should surface before taking action.
    """

    MIN_CONFIDENCE_PRECISE = 0.30   # threshold when file or command signal fired
    MIN_CONFIDENCE_SEMANTIC = 0.18  # threshold for semantic-only matches
    MAX_WARNINGS = 3

    def __init__(self, store, project_id: str, cache_dir: Optional[Path] = None):
        self.store = store
        self.project_id = project_id
        self.cache_dir = cache_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyse_prompt(self, prompt: str) -> List[FailureWarning]:
        """
        Return up to MAX_WARNINGS relevant failure warnings for this prompt.
        Returns an empty list when nothing is noteworthy.
        """
        try:
            failures = self.store.get_unresolved_failures(self.project_id, limit=100)
            if not failures:
                return []

            tfidf_scores = self._build_tfidf_scores(failures, prompt)

            prompt_lower = prompt.lower()
            ctx_files = set(_FILE_PAT.findall(prompt_lower))
            ctx_basenames = {
                f.rsplit('/', 1)[-1].rsplit('\\', 1)[-1] for f in ctx_files
            }
            ctx_cmds = set(_CMD_PAT.findall(prompt_lower))

            scored = []
            for node in failures:
                score, matched_on = self._score_failure(
                    node, prompt, tfidf_scores, ctx_files, ctx_basenames, ctx_cmds
                )
                threshold = (
                    self.MIN_CONFIDENCE_PRECISE
                    if matched_on in ("file", "command")
                    else self.MIN_CONFIDENCE_SEMANTIC
                )
                if score >= threshold:
                    resolution = self._get_resolution(node)
                    scored.append((FailureWarning(
                        error_type=node.data.get('error_type', 'error'),
                        error_summary=node.data.get('error_message', '')[:120],
                        resolution=resolution,
                        confidence=score,
                        matched_on=matched_on,
                        failure_node_id=node.id,
                        file=node.data.get('file'),
                    ), score))

            scored.sort(key=lambda x: x[1], reverse=True)
            return [w for w, _ in scored[:self.MAX_WARNINGS]]
        except Exception as e:
            logger.debug(f"FailureAdvisor.analyse_prompt failed (non-fatal): {e}")
            return []

    def format_warnings(self, warnings: List[FailureWarning]) -> str:
        """Format warnings as a compact markdown block for context injection."""
        if not warnings:
            return ""

        lines = ["**⚠ Failure History — Relevant Cautions:**"]
        for w in warnings:
            loc = f" in `{w.file}`" if w.file else ""
            lines.append(
                f"\n- **{w.error_type}**{loc} "
                f"(confidence {w.confidence:.0%}, matched on {w.matched_on})"
            )
            lines.append(f"  Error: {w.error_summary}")
            if w.resolution:
                lines.append(f"  Fix applied previously: {w.resolution}")
            else:
                lines.append(f"  Status: unresolved — proceed with care")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_tfidf_scores(self, failures, prompt: str) -> Dict[str, float]:
        """
        Build a failure-specific TF-IDF index and query it with the prompt.
        Returns {node_id: cosine_score}. Empty dict on any error or small corpus.
        """
        if len(failures) < _TFIDF_MIN_DOCS:
            return {}
        try:
            from similarity import get_or_build_index
            cache_dir = self.cache_dir or (
                Path.home() / ".claude" / "projects" / self.project_id / "graph_memory"
            )
            corpus = [
                (
                    n.id,
                    n.embedding_text
                    or f"{n.data.get('error_type', '')} {n.data.get('error_message', '')}"
                )
                for n in failures
            ]
            # Use a failure-specific cache key to avoid colliding with retrieval index
            idx = get_or_build_index(
                corpus,
                f"{self.project_id}_failures",
                cache_dir,
                ttl_seconds=120,
            )
            return {nid: sc for nid, sc in idx.query(prompt, top_k=len(corpus))}
        except Exception as e:
            logger.debug(f"TF-IDF index failed (Jaccard-only fallback): {e}")
            return {}

    def _score_failure(
        self,
        node,
        prompt: str,
        tfidf_scores: Dict[str, float],
        ctx_files: set,
        ctx_basenames: set,
        ctx_cmds: set,
    ) -> Tuple[float, str]:
        """Return (score, matched_on) where score is in [0, 1]."""
        score = 0.0
        matched_on = "semantic"
        data = node.data

        # Signal 1: file path match — strong precision signal (+0.55)
        fail_file = (data.get('file') or '').lower()
        fail_basename = fail_file.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
        if fail_file and (fail_file in ctx_files or fail_basename in ctx_basenames):
            score += 0.55
            matched_on = "file"

        # Signal 2: command or tool name match (+0.30)
        fail_cmd = (data.get('command') or '').lower()
        fail_tool = (data.get('tool') or '').lower()
        if fail_tool in ctx_cmds or any(c in fail_cmd for c in ctx_cmds if c):
            score += 0.30
            matched_on = matched_on if matched_on == "file" else "command"

        # Signal 3: TF-IDF + Jaccard hybrid (replaces snake_case-only keyword overlap)
        try:
            from similarity import lexical_jaccard_overlap
            embed = (
                node.embedding_text
                or f"{data.get('error_type', '')} {data.get('error_message', '')}"
            )
            jaccard = lexical_jaccard_overlap(prompt, embed)
            tfidf = tfidf_scores.get(node.id, 0.0)
            # Blend: prefer TF-IDF when available, Jaccard as reliable fallback
            semantic = (tfidf * 0.65 + jaccard * 0.35) if tfidf > 0 else jaccard
            score += semantic
        except Exception:
            pass

        return min(score, 1.0), matched_on

    def _get_resolution(self, failure_node) -> str:
        """
        Look up the resolution for a failure node.
        Priority: 1) failure.data.resolution field  2) RESOLVES edge → episode task
        """
        resolution = failure_node.data.get('resolution') or ''
        if resolution:
            return resolution[:200]

        try:
            from node_types import EdgeType
            edges = self.store.get_edges_to(failure_node.id, EdgeType.RESOLVES)
            if edges:
                fix_episode = self.store.get_node(edges[0].from_node)
                if fix_episode:
                    return fix_episode.data.get('task_description', '')[:200]
        except Exception:
            pass

        return ''
