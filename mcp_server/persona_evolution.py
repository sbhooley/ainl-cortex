"""
Zero-LLM persona evolution via soft axes.
Learn user preferences from behavior, not LLM introspection.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from datetime import datetime
import sqlite3
from pathlib import Path


@dataclass
class PersonaAxis:
    """Single persona axis with EMA evolution."""
    axis_name: str
    strength: float  # 0.0-1.0
    evolution_cycle: int
    last_updated: str


class PersonaAxes:
    """5 core persona axes."""

    INSTRUMENTALITY = "instrumentality"  # Prefers hands-on action vs guidance
    CURIOSITY = "curiosity"              # Explores new features actively
    PERSISTENCE = "persistence"          # Retries on failure vs gives up
    SYSTEMATICITY = "systematicity"      # Validates before acting
    VERBOSITY = "verbosity"              # Detailed explanations vs terse

    @staticmethod
    def all_axes() -> List[str]:
        return [
            PersonaAxes.INSTRUMENTALITY,
            PersonaAxes.CURIOSITY,
            PersonaAxes.PERSISTENCE,
            PersonaAxes.SYSTEMATICITY,
            PersonaAxes.VERBOSITY
        ]


@dataclass
class PersonaSignal:
    """Signal to update persona axes."""
    axis: str
    reward: float  # Target value (0.0-1.0)
    weight: float  # Signal strength (0.0-1.0)
    reason: str


class PersonaEvolutionEngine:
    """Evolve persona axes via weighted EMA."""

    EMA_ALPHA = 0.3  # Smoothing factor
    CORRECTION_RATE = 0.05  # Drift toward 0.5 when idle

    def __init__(self, db_path: Path, agent_id: str = "default"):
        self.db_path = db_path
        self.agent_id = agent_id
        self._init_schema()

    def _init_schema(self):
        """Initialize persona storage."""
        conn = sqlite3.connect(str(self.db_path))

        conn.execute("""
            CREATE TABLE IF NOT EXISTS persona_nodes (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                axis_name TEXT NOT NULL,
                strength REAL NOT NULL,
                evolution_cycle INTEGER NOT NULL,
                last_updated TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_persona_agent_axis
            ON persona_nodes(agent_id, axis_name)
        """)

        conn.commit()
        conn.close()

    def extract_signals(self, action: str, context: Dict) -> List[PersonaSignal]:
        """Extract persona signals from user action."""
        signals = []

        # AINL workflow creation → curiosity (exploring new tech)
        if action == "create_ainl_workflow":
            signals.append(PersonaSignal(
                axis=PersonaAxes.CURIOSITY,
                reward=0.75,
                weight=0.8,
                reason="User creating AINL workflow (exploring new tech)"
            ))

        # Validation before running → systematicity
        if action == "validate_before_run":
            signals.append(PersonaSignal(
                axis=PersonaAxes.SYSTEMATICITY,
                reward=0.85,
                weight=0.9,
                reason="User validates before running (methodical approach)"
            ))

        # Run immediately without validation → instrumentality
        if action == "run_immediately":
            signals.append(PersonaSignal(
                axis=PersonaAxes.INSTRUMENTALITY,
                reward=0.8,
                weight=0.7,
                reason="User runs immediately (hands-on, action-oriented)"
            ))

        # Retry after failure → persistence
        if action == "retry_after_failure":
            signals.append(PersonaSignal(
                axis=PersonaAxes.PERSISTENCE,
                reward=0.9,
                weight=0.85,
                reason="User retries after failure (persistent)"
            ))

        # Ask for detailed explanation → verbosity
        if action == "request_explanation":
            signals.append(PersonaSignal(
                axis=PersonaAxes.VERBOSITY,
                reward=0.8,
                weight=0.75,
                reason="User requests detailed explanation (prefers verbosity)"
            ))

        # Skip explanation, just do it → verbosity (low)
        if action == "skip_explanation":
            signals.append(PersonaSignal(
                axis=PersonaAxes.VERBOSITY,
                reward=0.2,
                weight=0.7,
                reason="User wants action without explanation (prefers terseness)"
            ))

        # Use template → systematicity (follows patterns)
        if action == "use_template":
            signals.append(PersonaSignal(
                axis=PersonaAxes.SYSTEMATICITY,
                reward=0.7,
                weight=0.6,
                reason="User uses template (systematic approach)"
            ))

        # Modify template → curiosity + instrumentality
        if action == "modify_template":
            signals.append(PersonaSignal(
                axis=PersonaAxes.CURIOSITY,
                reward=0.7,
                weight=0.6,
                reason="User modifies template (exploring variations)"
            ))
            signals.append(PersonaSignal(
                axis=PersonaAxes.INSTRUMENTALITY,
                reward=0.6,
                weight=0.5,
                reason="User hands-on customization"
            ))

        return signals

    def ingest_signals(self, signals: List[PersonaSignal]):
        """Apply signals to persona axes via weighted EMA."""
        if not signals:
            return

        conn = sqlite3.connect(str(self.db_path))

        for signal in signals:
            # Get current axis state
            cursor = conn.execute("""
                SELECT strength, evolution_cycle FROM persona_nodes
                WHERE agent_id = ? AND axis_name = ?
            """, (self.agent_id, signal.axis))

            row = cursor.fetchone()

            if row:
                current_strength, cycle = row
            else:
                # Initialize at 0.5 (neutral)
                current_strength = 0.5
                cycle = 0

            # Weighted EMA update
            # new_strength = current + alpha * (target - current)
            # where target = reward * weight
            delta = signal.reward * signal.weight - current_strength
            new_strength = current_strength + self.EMA_ALPHA * delta

            # Clamp to [0, 1]
            new_strength = max(0.0, min(1.0, new_strength))

            # Increment cycle
            new_cycle = cycle + 1

            now = datetime.utcnow().isoformat()

            # Upsert
            conn.execute("""
                INSERT INTO persona_nodes
                (id, agent_id, axis_name, strength, evolution_cycle, last_updated, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id, axis_name) DO UPDATE SET
                    strength = ?,
                    evolution_cycle = ?,
                    last_updated = ?
            """, (
                f"{self.agent_id}_{signal.axis}",
                self.agent_id,
                signal.axis,
                new_strength,
                new_cycle,
                now,
                now,
                new_strength,
                new_cycle,
                now
            ))

        conn.commit()
        conn.close()

    def correction_tick(self):
        """Drift axes toward 0.5 when no signals (prevents overfitting)."""
        conn = sqlite3.connect(str(self.db_path))

        cursor = conn.execute("""
            SELECT axis_name, strength, evolution_cycle FROM persona_nodes
            WHERE agent_id = ?
        """, (self.agent_id,))

        rows = cursor.fetchall()

        for axis_name, strength, cycle in rows:
            # Drift toward 0.5
            delta = 0.5 - strength
            new_strength = strength + self.CORRECTION_RATE * delta

            now = datetime.utcnow().isoformat()

            conn.execute("""
                UPDATE persona_nodes
                SET strength = ?, last_updated = ?
                WHERE agent_id = ? AND axis_name = ?
            """, (new_strength, now, self.agent_id, axis_name))

        conn.commit()
        conn.close()

    def get_active_traits(self, min_strength: float = 0.6) -> List[PersonaAxis]:
        """Get persona traits above strength threshold."""
        conn = sqlite3.connect(str(self.db_path))

        cursor = conn.execute("""
            SELECT axis_name, strength, evolution_cycle, last_updated
            FROM persona_nodes
            WHERE agent_id = ? AND strength >= ?
            ORDER BY strength DESC
        """, (self.agent_id, min_strength))

        rows = cursor.fetchall()
        conn.close()

        return [PersonaAxis(*row) for row in rows]

    def format_traits_for_prompt(self, min_strength: float = 0.6) -> str:
        """Format active traits for Claude context injection."""
        traits = self.get_active_traits(min_strength)

        if not traits:
            return ""

        lines = ["[User Persona Traits]"]
        for trait in traits:
            description = self._trait_description(trait.axis_name, trait.strength)
            lines.append(f"- {trait.axis_name}: {trait.strength:.2f} ({description})")

        return "\n".join(lines)

    def _trait_description(self, axis: str, strength: float) -> str:
        """Human-readable trait description."""
        if axis == PersonaAxes.INSTRUMENTALITY:
            if strength > 0.7:
                return "prefers hands-on action"
            elif strength < 0.3:
                return "prefers guidance and explanation"
            else:
                return "balanced action/guidance"

        elif axis == PersonaAxes.CURIOSITY:
            if strength > 0.7:
                return "actively explores new features"
            elif strength < 0.3:
                return "sticks to familiar patterns"
            else:
                return "moderate exploration"

        elif axis == PersonaAxes.PERSISTENCE:
            if strength > 0.7:
                return "retries multiple times on failure"
            elif strength < 0.3:
                return "gives up quickly on errors"
            else:
                return "moderate persistence"

        elif axis == PersonaAxes.SYSTEMATICITY:
            if strength > 0.7:
                return "validates before acting (methodical)"
            elif strength < 0.3:
                return "acts quickly without validation"
            else:
                return "balanced validation"

        elif axis == PersonaAxes.VERBOSITY:
            if strength > 0.7:
                return "prefers detailed explanations"
            elif strength < 0.3:
                return "prefers terse responses"
            else:
                return "balanced verbosity"

        return "neutral"

    def get_all_axes(self) -> Dict[str, PersonaAxis]:
        """Get all axes (including those below threshold)."""
        conn = sqlite3.connect(str(self.db_path))

        cursor = conn.execute("""
            SELECT axis_name, strength, evolution_cycle, last_updated
            FROM persona_nodes
            WHERE agent_id = ?
        """, (self.agent_id,))

        rows = cursor.fetchall()
        conn.close()

        result = {}
        for row in rows:
            axis = PersonaAxis(*row)
            result[axis.axis_name] = axis

        return result


def detect_action_from_context(
    prompt: str,
    previous_action: Optional[str] = None,
    validation_result: Optional[Dict] = None
) -> Optional[str]:
    """
    Detect user action from context for persona signal extraction.

    Args:
        prompt: User's prompt
        previous_action: Previous action (for retry detection)
        validation_result: Validation result (for validation detection)

    Returns:
        Action name or None
    """
    prompt_lower = prompt.lower()

    # Create AINL workflow
    if any(kw in prompt_lower for kw in ["create ainl", "ainl workflow", "write .ainl"]):
        return "create_ainl_workflow"

    # Validate before run
    if validation_result and validation_result.get("valid"):
        return "validate_before_run"

    # Run immediately (no validation)
    if any(kw in prompt_lower for kw in ["run it", "execute", "run this"]):
        if validation_result is None:
            return "run_immediately"

    # Retry after failure
    if previous_action and "failure" in str(previous_action):
        if any(kw in prompt_lower for kw in ["try again", "retry", "fix"]):
            return "retry_after_failure"

    # Request explanation
    if any(kw in prompt_lower for kw in ["explain", "how does", "why", "what does"]):
        return "request_explanation"

    # Skip explanation
    if any(kw in prompt_lower for kw in ["just do it", "skip", "no explanation"]):
        return "skip_explanation"

    # Use template
    if any(kw in prompt_lower for kw in ["use template", "from template"]):
        return "use_template"

    # Modify template
    if "modify" in prompt_lower or "customize" in prompt_lower or "change" in prompt_lower:
        if "template" in prompt_lower:
            return "modify_template"

    return None


__all__ = [
    'PersonaEvolutionEngine',
    'PersonaAxes',
    'PersonaSignal',
    'PersonaAxis',
    'detect_action_from_context'
]
