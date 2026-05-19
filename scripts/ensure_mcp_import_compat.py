#!/usr/bin/env python3
"""Preflight: heal node_types sys.modules alias (used by setup.sh and mcp_launch.sh)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_server.import_compat import ensure_node_types_alias, verify_bare_node_types_import

if __name__ == "__main__":
    ok = ensure_node_types_alias() and verify_bare_node_types_import()
    if not ok:
        print("warn: node_types import compat preflight did not fully heal", file=sys.stderr)
    sys.exit(0)  # never block install/launch on preflight
