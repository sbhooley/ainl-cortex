"""Upgrade runbook SessionStart banner."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_server.native_upgrade_runbook import format_banner


def test_format_banner_includes_runbook_header():
    state = {
        "store_backend": "python",
        "graph_memory_has_data": True,
        "ainl_native_importable": True,
        "unmigrated_project_hashes": ["abc123", "def456"],
        "recommended_actions": [
            {"type": "shell", "command": "bash scripts/upgrade_to_native.sh --yes", "id": "upgrade"},
            {"type": "user", "command": "/reload-plugins"},
        ],
    }
    text = format_banner(state)
    assert "UPGRADE RUNBOOK" in text
    assert "Unmigrated projects" in text
    assert "upgrade_to_native.sh" in text
    assert "/reload-plugins" in text
