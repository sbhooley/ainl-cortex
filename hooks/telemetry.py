"""
Fire-and-forget PostHog telemetry for ainl-cortex.

What is captured:
  install       — once when setup.sh runs (plugin version, OS, Python version)
  session_start — each Claude Code session (version, backend, OS)
  tool_used     — MCP tool name only, never arguments or user data

Nothing from user prompts, code, file paths, or memory DB is ever sent.
Opt-out: set "telemetry": {"remote": {"enabled": false}} in config.json
"""

from __future__ import annotations

import json
import platform
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict

POSTHOG_KEY = "phc_ovQDz0iHORAQ8vx2DyKiewAALjaFmpuXOgcI062lqMC"
POSTHOG_URL = "https://us.i.posthog.com/capture/"


def _load_config(plugin_root: Path) -> Dict[str, Any]:
    try:
        return json.loads((plugin_root / "config.json").read_text())
    except Exception:
        return {}


_PLUGIN_VERSION_CACHE: Dict[str, str] = {}


def _plugin_version(plugin_root: Path) -> str:
    """Read the canonical plugin version from .claude-plugin/plugin.json.

    Cached per plugin_root for the process lifetime so we don't stat the
    manifest on every PostHog event. Falls back to ``"unknown"`` if the
    manifest is missing or malformed — telemetry must never raise.
    """
    key = str(plugin_root)
    cached = _PLUGIN_VERSION_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        manifest = json.loads((plugin_root / ".claude-plugin" / "plugin.json").read_text())
        version = str(manifest.get("version") or "unknown")
    except Exception:
        version = "unknown"
    _PLUGIN_VERSION_CACHE[key] = version
    return version


def _is_enabled(config: Dict[str, Any]) -> bool:
    return bool(config.get("telemetry", {}).get("remote", {}).get("enabled", True))


def _install_id(config: Dict[str, Any]) -> str:
    return config.get("install_id", "unknown")


def _do_send(event: str, properties: Dict[str, Any], install_id: str) -> None:
    payload = json.dumps({
        "api_key": POSTHOG_KEY,
        "distinct_id": install_id,
        "event": event,
        "properties": {
            "$lib": "ainl-cortex",
            **properties,
        },
    }).encode()
    req = urllib.request.Request(
        POSTHOG_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3):
            pass
    except Exception:
        pass  # never raise — telemetry must never break the plugin


def capture(event: str, properties: Dict[str, Any], plugin_root: Path, blocking: bool = False) -> None:
    """Send a PostHog event. Event names are prefixed ainl_cortex_ automatically."""
    try:
        config = _load_config(plugin_root)
        if not _is_enabled(config):
            return
        iid = _install_id(config)
        prefixed = f"ainl_cortex_{event}"
        base = {
            "plugin_version": _plugin_version(plugin_root),
            "os": platform.system().lower(),
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
            **properties,
        }
        if blocking:
            _do_send(prefixed, base, iid)
        else:
            t = threading.Thread(target=_do_send, args=(prefixed, base, iid), daemon=True)
            t.start()
    except Exception:
        pass
