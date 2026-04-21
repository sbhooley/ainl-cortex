#!/usr/bin/env python3
"""AINL auto-validation hook for Claude Code.

Automatically validates .ainl files after tool use (Read/Edit/Write).
"""
import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# Try to import AINL tools
try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from mcp_server.ainl_tools import AINLTools, _HAS_AINL
    from mcp_server.failure_learning import FailureLearningStore
    _HAS_FAILURE_LEARNING = True
except ImportError:
    _HAS_AINL = False
    _HAS_FAILURE_LEARNING = False


class AINLValidator:
    """Auto-validates .ainl files with failure learning."""

    def __init__(self, project_id: Optional[str] = None):
        self.tools = AINLTools() if _HAS_AINL else None
        self.project_id = project_id

        # Initialize failure learning store
        self.failure_store = None
        if _HAS_FAILURE_LEARNING and project_id:
            try:
                failure_db = Path.home() / ".claude" / "projects" / project_id / "failures.db"
                failure_db.parent.mkdir(parents=True, exist_ok=True)
                self.failure_store = FailureLearningStore(failure_db)
            except Exception as e:
                sys.stderr.write(f"Failed to initialize failure store: {e}\n")
                self.failure_store = None

    def should_validate(self, event: Dict[str, Any]) -> Optional[str]:
        """
        Check if we should validate based on event.

        Returns:
            File path if should validate, None otherwise
        """
        # Check tool name
        tool_name = event.get("toolName", "")
        if tool_name not in ["Read", "Edit", "Write"]:
            return None

        # Check for .ainl file
        tool_input = event.get("toolInput", {})

        # Read/Edit: check file_path
        file_path = tool_input.get("file_path")
        if file_path and file_path.endswith(".ainl"):
            return file_path

        # Write: check file_path
        file_path = tool_input.get("file_path")
        if file_path and file_path.endswith(".ainl"):
            return file_path

        return None

    def validate_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Validate .ainl file and return diagnostics.

        Returns:
            Validation result or None if can't validate
        """
        if not self.tools:
            return None

        try:
            # Read file
            with open(file_path, 'r') as f:
                source = f.read()

            # Validate with strict mode
            result = self.tools.validate(source, strict=True)

            return result

        except FileNotFoundError:
            return None
        except Exception as e:
            return {
                "valid": False,
                "error": f"Validation error: {e}"
            }

    def format_validation_output(
        self,
        file_path: str,
        validation: Dict[str, Any],
        source: str
    ) -> str:
        """Format validation results as markdown with failure learning."""

        if validation.get("valid"):
            return f"""
**AINL Validation:** ✅ {Path(file_path).name}

{validation.get('message', 'Valid')}

**Next steps:** {', '.join(validation.get('recommended_next_tools', []))}
"""

        # Validation failed - check for similar failures
        diagnostics = validation.get("diagnostics", [])
        primary = validation.get("primary_diagnostic")

        output = f"""
**AINL Validation:** ❌ {Path(file_path).name}

"""

        if primary:
            output += f"**Error:** {primary.get('message', 'Unknown error')}\n"
            if "line" in primary:
                output += f"**Line:** {primary['line']}\n"
            output += "\n"

        # Record failure and check for similar issues
        if self.failure_store and primary:
            try:
                error_msg = primary.get('message', '')

                # Record this failure
                failure_id = self.failure_store.record_failure(
                    error_type=primary.get('error_type', 'validation_error'),
                    error_message=error_msg,
                    ainl_source=source,
                    context={'file': file_path}
                )

                # Search for similar failures with resolutions
                similar = self.failure_store.find_similar_failures(error_msg, limit=3)
                resolved = [f for f in similar if f.resolution]

                if resolved:
                    best_match = resolved[0]
                    output += f"\n**💡 I've seen this error before ({best_match.prevented_count} times).**\n"
                    output += f"**Previous fix:**\n```\n{best_match.resolution_diff}\n```\n\n"

            except Exception as e:
                sys.stderr.write(f"Failure learning error: {e}\n")

        repair_steps = validation.get("agent_repair_steps", [])
        if repair_steps:
            output += "**How to fix:**\n"
            for step in repair_steps:
                output += f"- {step}\n"
            output += "\n"

        if len(diagnostics) > 1:
            output += f"\n**{len(diagnostics) - 1} additional issue(s)**\n"

        resources = validation.get("recommended_resources", [])
        if resources:
            output += f"\n**Resources:** {', '.join(resources)}\n"

        return output


def main():
    """Hook entry point for PostToolUse."""
    if not _HAS_AINL:
        # Silently skip if AINL not installed
        return

    try:
        # Read event from stdin
        event = json.loads(sys.stdin.read())

        project_id = event.get("projectId")
        validator = AINLValidator(project_id=project_id)

        # Check if we should validate
        file_path = validator.should_validate(event)
        if not file_path:
            return

        # Read source for failure learning
        source = ""
        try:
            with open(file_path, 'r') as f:
                source = f.read()
        except Exception:
            pass

        # Validate
        validation = validator.validate_file(file_path)
        if not validation:
            return

        # Format output
        output_text = validator.format_validation_output(file_path, validation, source)

        # Output as context injection
        output = {
            "contextInjection": {
                "priority": "high",
                "content": output_text,
                "metadata": {
                    "source": "ainl_validator",
                    "file": file_path,
                    "valid": validation.get("valid", False)
                }
            }
        }

        print(json.dumps(output))

    except Exception as e:
        # Silent failure
        sys.stderr.write(f"AINL validator error: {e}\n")
        pass


if __name__ == "__main__":
    main()
