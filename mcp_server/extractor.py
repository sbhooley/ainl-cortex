"""
AINL Pattern Extraction

Procedural pattern extraction inspired by ainl-graph-extractor.
Detects repeated successful tool sequences and promotes them to procedural nodes.
"""

from typing import List, Dict, Any, Tuple
from collections import Counter, defaultdict
import re
import logging

try:
    from .node_types import NodeType
except ImportError:
    from node_types import NodeType

logger = logging.getLogger(__name__)


# Tool canonicalization map (inspired by ainl-semantic-tagger)
TOOL_CANONICALIZATION = {
    # Bash variants
    'Bash': 'bash', 'Shell': 'bash', 'sh': 'bash', 'shell': 'bash',
    # File operations
    'Read': 'read', 'FileRead': 'read', 'file_read': 'read',
    'Edit': 'edit', 'FileEdit': 'edit', 'file_edit': 'edit',
    'Write': 'write', 'FileWrite': 'write', 'file_write': 'write',
    # Search
    'Grep': 'grep', 'Search': 'grep', 'search': 'grep',
    'Glob': 'glob',
    # Web
    'WebSearch': 'web_search', 'WebFetch': 'web_fetch',
}


def canonicalize_tool(tool_name: str) -> str:
    """
    Canonicalize tool name to standard form.

    Follows AINL pattern: bash/shell/sh → bash
    """
    return TOOL_CANONICALIZATION.get(tool_name, tool_name.lower())


def canonicalize_tool_sequence(tools: List[str]) -> List[str]:
    """Canonicalize entire tool sequence"""
    return [canonicalize_tool(t) for t in tools]


class PatternExtractor:
    """
    Procedural pattern extraction (AINL graph-extractor pattern).

    Detects repeated successful tool sequences and promotes them
    to procedural nodes with fitness tracking.
    """

    MIN_OCCURRENCE = 2        # Minimum repetitions to promote
    MIN_FITNESS = 0.7         # Minimum success rate to promote
    MIN_SEQUENCE_LENGTH = 2   # Ignore single-tool "patterns"

    def extract_patterns(
        self,
        episodes: List[Dict[str, Any]],
        existing_patterns: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Extract procedural patterns from successful episodes.

        Returns:
            List of new pattern candidates with evidence and fitness scores
        """

        # Group episodes by canonicalized tool sequence signature
        sequences: Dict[Tuple[str, ...], List[Dict[str, Any]]] = defaultdict(list)

        for ep in episodes:
            # Only consider successful episodes
            if ep['data'].get('outcome') != 'success':
                continue

            # Get and canonicalize tool sequence
            raw_tools = ep['data'].get('tool_calls', [])
            canonical_tools = canonicalize_tool_sequence(raw_tools)

            # Skip trivial sequences
            if len(canonical_tools) < self.MIN_SEQUENCE_LENGTH:
                continue

            sig = tuple(canonical_tools)
            sequences[sig].append(ep)

        # Build existing pattern signatures to avoid duplicates
        existing_sigs = set()
        for pat in existing_patterns:
            sig = tuple(pat['data'].get('tool_sequence', []))
            existing_sigs.add(sig)

        # Promote sequences that meet thresholds
        new_patterns = []

        for sig, eps in sequences.items():
            # Skip if already exists
            if sig in existing_sigs:
                continue

            # Check occurrence threshold
            if len(eps) < self.MIN_OCCURRENCE:
                continue

            # Calculate fitness (simplified: success rate)
            # In practice, track failures too
            success_count = len(eps)
            failure_count = 0  # Would need to track these separately
            fitness = success_count / (success_count + failure_count + 1)

            if fitness < self.MIN_FITNESS:
                continue

            # Infer trigger from common context
            trigger = self._infer_trigger(eps)

            # Generate pattern name
            pattern_name = self._generate_pattern_name(sig, trigger)

            # Extract evidence IDs
            evidence_ids = [ep['data'].get('turn_id', ep['data'].get('id', '')) for ep in eps]

            new_patterns.append({
                'pattern_name': pattern_name,
                'trigger': trigger,
                'tool_sequence': list(sig),
                'success_count': success_count,
                'failure_count': failure_count,
                'fitness': fitness,
                'evidence_ids': evidence_ids,
                'scope': 'project'
            })

            logger.info(
                f"Promoted pattern '{pattern_name}': "
                f"{' → '.join(sig)} (fitness: {fitness:.2f}, n={success_count})"
            )

        return new_patterns

    def _infer_trigger(self, episodes: List[Dict[str, Any]]) -> str:
        """
        Infer common trigger from episode contexts.

        Uses simple word frequency analysis on task descriptions.
        """
        descriptions = [ep['data'].get('task_description', '') for ep in episodes]

        # Extract words
        all_words = []
        for desc in descriptions:
            words = re.findall(r'\b\w+\b', desc.lower())
            # Filter stopwords
            words = [w for w in words if len(w) > 3 and w not in {
                'the', 'this', 'that', 'with', 'from', 'have', 'been', 'were'
            }]
            all_words.extend(words)

        if not all_words:
            return "unknown trigger"

        # Get most common words
        common = Counter(all_words).most_common(3)
        trigger_words = [word for word, count in common if count > 1]

        if not trigger_words:
            # Fallback to first episode's task (truncated)
            first_task = descriptions[0] if descriptions else "unknown"
            return first_task[:30]

        return ' '.join(trigger_words)

    def _generate_pattern_name(self, sequence: Tuple[str, ...], trigger: str) -> str:
        """Generate descriptive pattern name"""
        # Use trigger + tool sequence preview
        tool_str = '-'.join(sequence[:3])

        # Clean trigger
        trigger_clean = re.sub(r'[^\w\s]', '', trigger)
        trigger_parts = trigger_clean.split()[:3]
        trigger_str = '-'.join(trigger_parts)

        if not trigger_str:
            trigger_str = 'workflow'

        name = f"{trigger_str}-{tool_str}"

        # Limit length
        if len(name) > 50:
            name = name[:47] + '...'

        return name

    def update_pattern_fitness(
        self,
        pattern: Dict[str, Any],
        success: bool,
        alpha: float = 0.2
    ) -> float:
        """
        Update pattern fitness using EMA (Exponential Moving Average).

        Args:
            pattern: Pattern dict with fitness field
            success: Whether latest use was successful
            alpha: EMA smoothing factor (0.0-1.0)

        Returns:
            Updated fitness score
        """
        current_fitness = pattern.get('fitness', 1.0)
        outcome_score = 1.0 if success else 0.0

        # EMA update: new = alpha * outcome + (1 - alpha) * old
        new_fitness = alpha * outcome_score + (1 - alpha) * current_fitness

        pattern['fitness'] = new_fitness

        # Update counts
        if success:
            pattern['success_count'] = pattern.get('success_count', 0) + 1
        else:
            pattern['failure_count'] = pattern.get('failure_count', 0) + 1

        logger.debug(
            f"Updated pattern '{pattern['pattern_name']}' fitness: "
            f"{current_fitness:.2f} → {new_fitness:.2f}"
        )

        return new_fitness
