#!/usr/bin/env python3
"""AINL auto-validation hook for Claude Code.

Automatically validates .ainl files after tool use (Read/Edit/Write).
"""
import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional

sys.path.insert(0, str(Path(__file__).parent))
from shared.project_id import get_project_id

# Try to import AINL tools
try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from mcp_server.ainl_tools import AINLTools, _HAS_AINL
except ImportError:
    _HAS_AINL = False


class AINLValidator:
    """Auto-validates .ainl files after Edit/Write tool use."""

    def __init__(self, project_id: Optional[str] = None):
        self.tools = AINLTools() if _HAS_AINL else None
        self.project_id = project_id

    def should_validate(self, event: Dict[str, Any]) -> Optional[str]:
        """
        Check if we should validate based on event.

        Returns:
            File path if should validate, None otherwise
        """
        # Claude Code PostToolUse payload uses snake_case field names
        tool_name = event.get("tool_name", "")
        if tool_name not in ["Edit", "Write"]:
            # Read doesn't change the file — no point re-validating on read
            return None

        tool_input = event.get("tool_input", {}) or {}
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
            with open(file_path, 'r', encoding='utf-8') as f:
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

    def format_validation_output(self, file_path: str, validation: Dict[str, Any]) -> str:
        """Format validation results as a compact markdown block."""
        name = Path(file_path).name

        if validation.get("valid"):
            next_tools = validation.get('recommended_next_tools', [])
            msg = validation.get('message', 'Valid')
            out = f"**AINL Validation:** ✅ {name}\n{msg}"
            if next_tools:
                out += f"\n**Next steps:** {', '.join(next_tools)}"
            return out

        diagnostics = validation.get("diagnostics", [])
        primary = validation.get("primary_diagnostic")

        out = f"**AINL Validation:** ❌ {name}\n"
        if primary:
            out += f"**Error:** {primary.get('message', 'Unknown error')}\n"
            if "line" in primary:
                out += f"**Line:** {primary['line']}\n"

        repair_steps = validation.get("agent_repair_steps", [])
        if repair_steps:
            out += "**How to fix:**\n" + "".join(f"- {s}\n" for s in repair_steps)

        if len(diagnostics) > 1:
            out += f"\n**{len(diagnostics) - 1} additional issue(s)**"

        resources = validation.get("recommended_resources", [])
        if resources:
            out += f"\n**Resources:** {', '.join(resources)}"

        return out


def main():
    """Hook entry point for PostToolUse."""
    if not _HAS_AINL:
        # Silently skip if AINL not installed
        return

    try:
        from shared.stdin import read_stdin_json
        event = read_stdin_json(hook_name="ainl_validator")

        # projectId is not in PostToolUse payloads — compute from cwd
        cwd = Path(event.get("cwd", str(Path.cwd())))
        project_id = get_project_id(cwd)
        validator = AINLValidator(project_id=project_id)

        # Check if we should validate
        file_path = validator.should_validate(event)
        if not file_path:
            return

        # Validate
        validation = validator.validate_file(file_path)
        if not validation:
            return

        # Format output
        output_text = validator.format_validation_output(file_path, validation)

        # PostToolUse context injection: hookSpecificOutput.additionalContext
        output = {
            "hookSpecificOutput": {
                "additionalContext": output_text
            }
        }

        print(json.dumps(output))

    except Exception as e:
        # Silent failure
        sys.stderr.write(f"AINL validator error: {e}\n")
        pass


if __name__ == "__main__":
    main()
