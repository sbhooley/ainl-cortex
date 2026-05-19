#!/usr/bin/env python3
"""
Mechanical codemod: bare mcp_server imports → relative imports.

Usage (from plugin root):
    python3 scripts/codemod_relative_imports.py [--check]

Idempotent for files already converted. Re-run after adding new mcp_server modules
that use legacy bare imports.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
MCP = PLUGIN_ROOT / "mcp_server"

LOCAL = {
    "node_types", "graph_store", "retrieval", "similarity", "native_graph_store",
    "native_compat", "migration_compat",
    "persona_engine", "extractor", "goal_tracker", "ainl_tools", "a2a_tools",
    "config", "compression", "compression_pipeline", "output_compression",
    "project_profiles", "cache_awareness", "adaptive_eco", "failure_advisor",
    "memory_reconcile", "anchored_summary", "a2a_store",
}

SKIP = {"import_compat.py", "codemod_relative_imports.py"}


def transform(content: str) -> str:
    for mod in sorted(LOCAL, key=len, reverse=True):
        pat = re.compile(
            rf"try:\n(    from \.{mod} import[^\n]+\n)except ImportError:\n    from {mod} import[^\n]+\n",
            re.MULTILINE,
        )
        content = pat.sub(r"\1", content)
    for mod in LOCAL:
        content = re.sub(
            rf"(?<!\.)(?<!\w)from {mod} import",
            f"from .{mod} import",
            content,
        )
    return content


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="Exit 1 if changes would be made")
    args = ap.parse_args()
    changed = []
    for path in sorted(MCP.glob("*.py")):
        if path.name in SKIP:
            continue
        orig = path.read_text()
        new = transform(orig)
        if new != orig:
            changed.append(path.name)
            if not args.check:
                path.write_text(new)
    if changed:
        print("would change:" if args.check else "changed:", ", ".join(changed))
        return 1 if args.check else 0
    print("all mcp_server imports already relative")
    return 0


if __name__ == "__main__":
    sys.exit(main())
