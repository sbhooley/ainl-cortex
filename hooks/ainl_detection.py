#!/usr/bin/env python3
"""AINL opportunity detection hook for Claude Code.

Detects when to suggest using .ainl files based on user prompts and context.
Includes persona evolution tracking.
"""
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from mcp_server.persona_evolution import (
        PersonaEvolutionEngine,
        detect_action_from_context
    )
    PERSONA_AVAILABLE = True
except ImportError:
    PERSONA_AVAILABLE = False


# Trigger keywords that suggest AINL usage
RECURRING_KEYWORDS = [
    "every", "hourly", "daily", "weekly", "monthly",
    "monitor", "check", "recurring", "scheduled", "cron",
    "repeatedly", "periodic", "regular", "automation"
]

WORKFLOW_KEYWORDS = [
    "workflow", "automation", "pipeline", "process",
    "multi-step", "sequence", "orchestrate", "coordinate"
]

API_KEYWORDS = [
    "api", "endpoint", "fetch", "http", "webhook",
    "rest", "call", "request", "integration"
]

BLOCKCHAIN_KEYWORDS = [
    "solana", "blockchain", "wallet", "crypto", "token",
    "nft", "defi", "web3", "balance", "transfer"
]

COST_KEYWORDS = [
    "cost", "expensive", "budget", "save", "cheap",
    "token", "efficient", "optimize"
]

CONDITIONAL_KEYWORDS = [
    "if", "when", "then", "else", "condition",
    "check if", "depending on", "based on"
]


class AINLDetector:
    """Detects opportunities to suggest AINL."""

    def __init__(self, project_id: Optional[str] = None):
        self.confidence_threshold = 0.6
        self.project_id = project_id

        # Initialize persona engine if available
        self.persona_engine = None
        if PERSONA_AVAILABLE and project_id:
            try:
                persona_db = Path.home() / ".claude" / "projects" / project_id / "persona.db"
                persona_db.parent.mkdir(parents=True, exist_ok=True)
                self.persona_engine = PersonaEvolutionEngine(persona_db)
            except Exception as e:
                sys.stderr.write(f"Failed to initialize persona engine: {e}\n")
                self.persona_engine = None

    def analyze_prompt(self, prompt: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze user prompt to detect AINL opportunities.

        Args:
            prompt: User's message
            context: Additional context (working dir, files, etc.)

        Returns:
            {
                "suggest_ainl": bool,
                "confidence": float (0-1),
                "reasons": List[str],
                "use_case": str,
                "suggestion_text": str (markdown)
            }
        """
        prompt_lower = prompt.lower()
        reasons = []
        confidence_score = 0.0

        # Check for .ainl files in workspace
        has_ainl_files = self._check_ainl_files(context)
        if has_ainl_files:
            confidence_score += 0.2
            reasons.append("Existing .ainl files in workspace")

        # Check for recurring/scheduled patterns
        recurring_matches = sum(1 for kw in RECURRING_KEYWORDS if kw in prompt_lower)
        if recurring_matches > 0:
            confidence_score += min(0.4, recurring_matches * 0.15)
            reasons.append(f"Recurring pattern detected ({recurring_matches} keywords)")

        # Check for workflow patterns
        workflow_matches = sum(1 for kw in WORKFLOW_KEYWORDS if kw in prompt_lower)
        if workflow_matches > 0:
            confidence_score += min(0.3, workflow_matches * 0.15)
            reasons.append(f"Workflow pattern detected ({workflow_matches} keywords)")

        # Check for API integration
        api_matches = sum(1 for kw in API_KEYWORDS if kw in prompt_lower)
        if api_matches > 1:
            confidence_score += min(0.25, api_matches * 0.1)
            reasons.append("API integration detected")

        # Check for blockchain
        blockchain_matches = sum(1 for kw in BLOCKCHAIN_KEYWORDS if kw in prompt_lower)
        if blockchain_matches > 0:
            confidence_score += 0.5  # Strong signal
            reasons.append("Blockchain interaction detected (AINL has Solana adapter)")

        # Check for cost concerns
        cost_matches = sum(1 for kw in COST_KEYWORDS if kw in prompt_lower)
        if cost_matches > 0:
            confidence_score += 0.3
            reasons.append("Cost/efficiency concern detected")

        # Check for conditional logic
        conditional_matches = sum(1 for kw in CONDITIONAL_KEYWORDS if kw in prompt_lower)
        if conditional_matches > 1:
            confidence_score += 0.2
            reasons.append("Conditional logic detected")

        # Determine use case
        use_case = self._determine_use_case(
            prompt_lower,
            recurring_matches,
            workflow_matches,
            blockchain_matches,
            api_matches
        )

        # Cap confidence at 1.0
        confidence_score = min(1.0, confidence_score)

        # Extract persona signals from prompt
        if self.persona_engine and PERSONA_AVAILABLE:
            try:
                action = detect_action_from_context(prompt)
                if action:
                    signals = self.persona_engine.extract_signals(action, context)
                    if signals:
                        self.persona_engine.ingest_signals(signals)
            except Exception as e:
                sys.stderr.write(f"Persona signal extraction failed: {e}\n")

        # Generate suggestion text
        suggestion_text = ""
        persona_traits = ""

        if confidence_score >= self.confidence_threshold:
            suggestion_text = self._generate_suggestion(
                use_case, confidence_score, reasons
            )

            # Add persona traits if available
            if self.persona_engine:
                try:
                    persona_traits = self.persona_engine.format_traits_for_prompt(min_strength=0.6)
                except Exception as e:
                    sys.stderr.write(f"Persona trait formatting failed: {e}\n")

        return {
            "suggest_ainl": confidence_score >= self.confidence_threshold,
            "confidence": round(confidence_score, 2),
            "reasons": reasons,
            "use_case": use_case,
            "suggestion_text": suggestion_text,
            "persona_traits": persona_traits
        }

    def _check_ainl_files(self, context: Dict[str, Any]) -> bool:
        """Check if .ainl files exist in workspace."""
        working_dir = context.get("workingDir")
        if not working_dir:
            return False

        try:
            workspace = Path(working_dir)
            ainl_files = list(workspace.glob("**/*.ainl"))
            return len(ainl_files) > 0
        except Exception:
            return False

    def _determine_use_case(
        self,
        prompt: str,
        recurring: int,
        workflow: int,
        blockchain: int,
        api: int
    ) -> str:
        """Determine the primary use case."""
        if blockchain > 0:
            return "blockchain_monitor"
        if recurring > 1:
            return "recurring_monitor"
        if workflow > 0 and api > 0:
            return "api_workflow"
        if workflow > 0:
            return "automation"
        if api > 0:
            return "api_integration"
        return "general_workflow"

    def _generate_suggestion(
        self,
        use_case: str,
        confidence: float,
        reasons: List[str]
    ) -> str:
        """Generate suggestion text based on use case."""

        base_savings = """

**Token Savings:** AINL compiles once (~200 tokens) then executes at ~5 tokens per run.
For recurring tasks, this saves 90-95% compared to regenerating code each time.
"""

        suggestions = {
            "blockchain_monitor": f"""
I recommend creating this as an **AINL workflow** (.ainl file).

**Why AINL for blockchain:**
- Specialized Solana adapter with 1447 lines of blockchain operations
- Deterministic execution for financial operations
- Built-in scheduling for monitors
{base_savings}

Would you like me to create a .ainl workflow for this?
""",
            "recurring_monitor": f"""
I recommend creating this as an **AINL workflow** (.ainl file).

**Why AINL for monitoring:**
- Built-in cron scheduling
- Compile once, run repeatedly
- Ideal for recurring checks
{base_savings}

Would you like me to create a .ainl monitor for this?
""",
            "api_workflow": f"""
I recommend creating this as an **AINL workflow** (.ainl file).

**Why AINL for API workflows:**
- Graph-native multi-step execution
- Explicit dataflow and error handling
- 50+ adapters for APIs, databases, etc.
{base_savings if confidence > 0.7 else ""}

Would you like me to create a .ainl workflow for this?
""",
            "automation": f"""
I recommend creating this as an **AINL workflow** (.ainl file).

**Why AINL for automation:**
- Deterministic graph execution
- Type-safe, validated workflows
- Easy to test and maintain
{base_savings if confidence > 0.7 else ""}

Would you like me to create a .ainl automation?
""",
            "general_workflow": f"""
Consider using an **AINL workflow** (.ainl file) for this.

**Benefits:**
- Graph-based execution (more deterministic than scripts)
- 50+ adapters for common integrations
- Can emit to Python/TS later if needed

Would you like to try AINL for this?
"""
        }

        return suggestions.get(use_case, suggestions["general_workflow"])


def main():
    """Hook entry point for UserPromptSubmit."""
    try:
        # Read event from stdin
        event = json.loads(sys.stdin.read())

        prompt = event.get("prompt", "")
        project_id = event.get("projectId")
        context = {
            "workingDir": event.get("workingDir"),
            "projectId": project_id
        }

        # Analyze
        detector = AINLDetector(project_id=project_id)
        result = detector.analyze_prompt(prompt, context)

        # Only output if we should suggest
        if result["suggest_ainl"]:
            # Combine suggestion with persona traits
            content = result["suggestion_text"]
            if result.get("persona_traits"):
                content = f"{result['persona_traits']}\n\n{content}"

            # Output suggestion as context injection
            output = {
                "contextInjection": {
                    "priority": "medium",
                    "content": content,
                    "metadata": {
                        "source": "ainl_detection",
                        "confidence": result["confidence"],
                        "use_case": result["use_case"],
                        "reasons": result["reasons"]
                    }
                }
            }
            print(json.dumps(output))

    except Exception as e:
        # Silent failure - don't break Claude Code
        sys.stderr.write(f"AINL detection error: {e}\n")
        pass


if __name__ == "__main__":
    main()
