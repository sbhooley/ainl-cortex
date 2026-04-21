"""
Multi-turn context compilation for AINL interactions.
Assembles memory blocks with budget management.
"""

import sqlite3
from typing import Dict, List, Optional, Any
from pathlib import Path
from dataclasses import dataclass


@dataclass
class ContextBlock:
    """Single context block with priority and token estimate."""
    name: str
    content: str
    priority: int  # 1 (high) to 3 (low)
    token_estimate: int


class AINLContextCompiler:
    """Compile context from multiple memory sources."""

    def __init__(
        self,
        trajectory_db: Optional[Path] = None,
        pattern_db: Optional[Path] = None,
        persona_db: Optional[Path] = None,
        failure_db: Optional[Path] = None
    ):
        self.trajectory_db = trajectory_db
        self.pattern_db = pattern_db
        self.persona_db = persona_db
        self.failure_db = failure_db

    def compile_context(
        self,
        session_id: Optional[str] = None,
        project_id: Optional[str] = None,
        max_tokens: int = 500,
        include_blocks: Optional[List[str]] = None
    ) -> str:
        """
        Compile context from memory sources.

        Args:
            session_id: Current session ID
            project_id: Current project ID
            max_tokens: Maximum token budget
            include_blocks: Which blocks to include (None = all)

        Returns:
            Compiled context as markdown
        """
        if include_blocks is None:
            include_blocks = [
                'recent_attempts',
                'known_facts',
                'suggested_patterns',
                'active_traits'
            ]

        blocks = []

        # 1. Recent AINL attempts (session-specific, high priority)
        if 'recent_attempts' in include_blocks and self.trajectory_db:
            recent = self._get_recent_attempts(session_id, limit=3)
            if recent:
                blocks.append(ContextBlock(
                    name='recent_attempts',
                    content=recent,
                    priority=1,
                    token_estimate=self._estimate_tokens(recent)
                ))

        # 2. Known facts (semantic, medium-high priority)
        if 'known_facts' in include_blocks and self.pattern_db:
            facts = self._get_known_facts(project_id, limit=5)
            if facts:
                blocks.append(ContextBlock(
                    name='known_facts',
                    content=facts,
                    priority=2,
                    token_estimate=self._estimate_tokens(facts)
                ))

        # 3. Suggested patterns (procedural, medium priority)
        if 'suggested_patterns' in include_blocks and self.pattern_db:
            patterns = self._get_suggested_patterns(project_id, limit=3)
            if patterns:
                blocks.append(ContextBlock(
                    name='suggested_patterns',
                    content=patterns,
                    priority=2,
                    token_estimate=self._estimate_tokens(patterns)
                ))

        # 4. Active persona traits (high priority)
        if 'active_traits' in include_blocks and self.persona_db:
            traits = self._get_active_traits()
            if traits:
                blocks.append(ContextBlock(
                    name='active_traits',
                    content=traits,
                    priority=1,
                    token_estimate=self._estimate_tokens(traits)
                ))

        # Budget management: prioritize and truncate
        selected_blocks = self._apply_budget(blocks, max_tokens)

        # Assemble final context
        if not selected_blocks:
            return ""

        context_parts = []
        for block in selected_blocks:
            context_parts.append(block.content)

        return "\n\n".join(context_parts)

    def _get_recent_attempts(self, session_id: Optional[str], limit: int) -> str:
        """Get recent AINL execution attempts."""
        if not self.trajectory_db or not self.trajectory_db.exists():
            return ""

        try:
            from mcp_server.trajectory_capture import TrajectoryStore

            store = TrajectoryStore(self.trajectory_db)
            if not session_id:
                return ""

            trajectories = store.get_recent_trajectories(session_id, limit=limit)
            if not trajectories:
                return ""

            lines = ["[Recent AINL Activity]"]
            for traj in trajectories:
                outcome_icon = "✅" if traj.outcome == "success" else "❌"
                lines.append(
                    f"- {outcome_icon} {traj.executed_at[:10]}: "
                    f"{len(traj.steps)} steps, {traj.duration_ms:.0f}ms"
                )
                if traj.tags:
                    lines.append(f"  Adapters: {', '.join(traj.tags)}")

            return "\n".join(lines)

        except Exception:
            return ""

    def _get_known_facts(self, project_id: Optional[str], limit: int) -> str:
        """Get top ranked semantic facts."""
        if not self.pattern_db or not self.pattern_db.exists():
            return ""

        try:
            from mcp_server.ainl_patterns import AINLPatternStore

            store = AINLPatternStore(str(self.pattern_db))
            facts = store.get_ranked_facts(
                project_id=project_id,
                min_confidence=0.5,
                limit=limit
            )

            if not facts:
                return ""

            lines = ["[Known AINL Patterns]"]
            for fact in facts:
                lines.append(
                    f"- {fact['description']} "
                    f"(confidence: {fact['fitness_score']:.2f}, "
                    f"used {fact['uses']}× times)"
                )

            return "\n".join(lines)

        except Exception:
            return ""

    def _get_suggested_patterns(self, project_id: Optional[str], limit: int) -> str:
        """Get high-fitness reusable patterns."""
        if not self.pattern_db or not self.pattern_db.exists():
            return ""

        try:
            from mcp_server.ainl_patterns import AINLPatternStore

            store = AINLPatternStore(str(self.pattern_db))
            patterns = store.get_ranked_facts(
                project_id=project_id,
                min_confidence=0.6,
                limit=limit
            )

            if not patterns:
                return ""

            lines = ["[Reusable Patterns]"]
            for pattern in patterns:
                if pattern['pattern_type'] == 'Procedural':
                    lines.append(
                        f"- {pattern['description']} "
                        f"(fitness: {pattern['fitness_score']:.2f})"
                    )
                    # Add snippet
                    source_lines = pattern['ainl_source'].split('\n')[:3]
                    snippet = '\n'.join(f"  {line}" for line in source_lines)
                    lines.append(snippet)

            return "\n".join(lines)

        except Exception:
            return ""

    def _get_active_traits(self) -> str:
        """Get active persona traits."""
        if not self.persona_db or not self.persona_db.exists():
            return ""

        try:
            from mcp_server.persona_evolution import PersonaEvolutionEngine

            engine = PersonaEvolutionEngine(self.persona_db)
            traits_text = engine.format_traits_for_prompt(min_strength=0.6)

            return traits_text if traits_text else ""

        except Exception:
            return ""

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count (rough approximation)."""
        # Rough estimate: 1 token ≈ 4 characters
        return len(text) // 4

    def _apply_budget(
        self,
        blocks: List[ContextBlock],
        max_tokens: int
    ) -> List[ContextBlock]:
        """
        Apply token budget to blocks.

        Strategy:
        1. Sort by priority (1 = high first)
        2. Include blocks until budget exhausted
        3. Fail-closed: skip low-quality blocks
        """
        # Sort by priority (ascending: 1, 2, 3)
        blocks.sort(key=lambda b: b.priority)

        selected = []
        used_tokens = 0

        for block in blocks:
            if used_tokens + block.token_estimate <= max_tokens:
                selected.append(block)
                used_tokens += block.token_estimate
            else:
                # Try to fit a compressed version for low-priority blocks
                if block.priority >= 2:
                    # Skip low-priority blocks when budget tight
                    continue
                else:
                    # High-priority blocks: truncate if needed
                    remaining = max_tokens - used_tokens
                    if remaining > 50:  # Min useful size
                        truncated_content = block.content[:remaining * 4]
                        selected.append(ContextBlock(
                            name=block.name,
                            content=truncated_content + "...",
                            priority=block.priority,
                            token_estimate=remaining
                        ))
                    break

        return selected


__all__ = ['AINLContextCompiler', 'ContextBlock']
