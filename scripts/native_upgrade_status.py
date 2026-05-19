#!/usr/bin/env python3
"""Machine-readable native upgrade status for Claude Code (read before upgrading)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))

from mcp_server.native_upgrade_runbook import (  # noqa: E402
    assess,
    execute_recommended,
    format_banner,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="AINL Cortex native upgrade status")
    parser.add_argument("--json", action="store_true", help="JSON only on stdout")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run recommended shell actions (non-interactive)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="With --execute, print commands without running",
    )
    args = parser.parse_args()

    if args.execute:
        state = execute_recommended(PLUGIN_ROOT, dry_run=args.dry_run)
    else:
        state = assess(PLUGIN_ROOT)

    if args.json:
        print(json.dumps(state, indent=2))
    else:
        print(format_banner(state) or json.dumps(state, indent=2))
        if args.execute:
            print("\nExecute results:")
            print(json.dumps(state.get("execute_results", []), indent=2))
            ok = state.get("execute_ok", False)
            for act in state.get("recommended_actions", []):
                if act.get("type") == "user":
                    print("\n" + act.get("message", ""))
            return 0 if ok else 1

    if args.execute and not state.get("execute_ok", True):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
