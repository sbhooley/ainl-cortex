"""Verify A2A tools are advertised + dispatched only when enabled in config.

Covers Issue B1 from the post-fix audit. Two regression scenarios:

1. ``config.a2a.enabled = False`` → no tool whose name starts with ``a2a_``
   appears in ``list_tools`` output, and a direct ``call_tool`` dispatch for
   one of those names returns a structured ``feature_disabled`` envelope
   rather than 500-ing or silently executing.
2. ``config.a2a.enabled = True`` → all 7 a2a tools are advertised.

The test mutates ``memory_server._a2a_enabled`` directly (post-init) instead
of reconstructing the server, because ``AINLGraphMemoryServer.__init__``
loads config from ``config.json`` on disk and we want a hermetic test.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "mcp_server"))


def _import_server():
    import server as srv  # type: ignore
    return srv


def _list_tools_sync(srv) -> list:
    return asyncio.run(srv.list_tools())


def _call_tool_sync(srv, name: str, args: dict) -> list:
    return asyncio.run(srv.call_tool(name, args))


_A2A_NAMES = {
    "a2a_send",
    "a2a_list_agents",
    "a2a_register_agent",
    "a2a_note_to_self",
    "a2a_register_monitor",
    "a2a_task_send",
    "a2a_task_status",
}


def test_a2a_tools_hidden_when_disabled():
    srv = _import_server()
    srv.memory_server._a2a_enabled = False

    advertised = {t.name for t in _list_tools_sync(srv)}
    assert advertised.isdisjoint(_A2A_NAMES), (
        f"A2A tools must not be advertised when disabled, got: "
        f"{sorted(advertised & _A2A_NAMES)}"
    )


def test_a2a_call_tool_returns_feature_disabled_when_off():
    srv = _import_server()
    srv.memory_server._a2a_enabled = False

    result = _call_tool_sync(srv, "a2a_list_agents", {})
    assert len(result) == 1
    payload = json.loads(result[0].text)
    assert payload["ok"] is False
    assert payload["error_type"] == "feature_disabled"


def test_a2a_tools_advertised_when_enabled():
    srv = _import_server()
    srv.memory_server._a2a_enabled = True

    advertised = {t.name for t in _list_tools_sync(srv)}
    missing = _A2A_NAMES - advertised
    assert not missing, f"Expected a2a tools advertised when enabled, missing: {sorted(missing)}"
