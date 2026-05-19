#!/usr/bin/env python3
"""Preflight: full runtime bootstrap (install, MCP launch, CI)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_server.build_stamp import write_install_stamp
from mcp_server.import_compat import (
    verify_bare_graph_store_import,
    verify_bare_node_types_import,
    verify_bare_retrieval_import,
)
from mcp_server.runtime_bootstrap import bootstrap_runtime

if __name__ == "__main__":
    write_install_stamp(ROOT)
    ok, detail = bootstrap_runtime(ROOT, heal_deps=True)
    try:
        from mcp_server.mcp_reload import request_mcp_reload
        request_mcp_reload(ROOT, reason="setup_or_preflight")
    except Exception:
        pass
    checks = (
        verify_bare_node_types_import(),
        verify_bare_graph_store_import(),
        verify_bare_retrieval_import(),
    )
    if not all(checks):
        print(
            f"warn: runtime preflight incomplete ({detail}); "
            f"node_types={checks[0]} graph_store={checks[1]} retrieval={checks[2]}",
            file=sys.stderr,
        )
    elif not ok:
        print(f"warn: runtime bootstrap: {detail}", file=sys.stderr)
    sys.exit(0)
