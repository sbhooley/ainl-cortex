#!/usr/bin/env python3
"""
Notification poller for ainl-cortex.

Fetches https://www.ainativelang.com/notifications once per session, filters for
this plugin, surfaces unseen entries in the SessionStart banner, and optionally
applies auto-updates when the server marks a release safe.

Client algorithm (matches server contract):
  1. Require schema_version == 1 (forward-compat: accept > 1 silently too).
  2. Filter: targets must include "claude-code-plugin" or "*".
  3. Drop: expires_at present and now > expires_at.
  4. Sort: priority desc (default 0), then published_at desc.
  5. Auto-update: enabled + artifact == "ainl-cortex" + version in range.
"""

import json
import os
import ssl
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _ssl_context() -> ssl.SSLContext:
    """Return an SSL context that works on macOS without system cert config."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    return ssl.create_default_context()

NOTIFICATIONS_URL = "https://www.ainativelang.com/notifications"
PLUGIN_ARTIFACT = "ainl-cortex"
OUR_TARGETS: frozenset = frozenset({"claude-code-plugin", "*"})
SEEN_FILE_REL = Path("a2a") / "notifications_seen.json"
PLUGIN_JSON_REL = Path(".claude-plugin") / "plugin.json"


# ── version helpers ────────────────────────────────────────────────────────────

def _read_plugin_version(plugin_root: Path) -> str:
    try:
        data = json.loads((plugin_root / PLUGIN_JSON_REL).read_text())
        return str(data.get("version", "0.0.0"))
    except Exception:
        return "0.0.0"


def _ver_tuple(v: str) -> Tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split(".")[:3])
    except Exception:
        return (0, 0, 0)


def _version_in_range(current: str, min_v: Optional[str], max_v: Optional[str]) -> bool:
    cur = _ver_tuple(current)
    if min_v is not None and cur < _ver_tuple(min_v):
        return False
    if max_v is not None and cur > _ver_tuple(max_v):
        return False
    return True


# ── datetime helper ────────────────────────────────────────────────────────────

def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


# ── seen-ID persistence ────────────────────────────────────────────────────────

def _load_seen(plugin_root: Path) -> set:
    path = plugin_root / SEEN_FILE_REL
    try:
        data = json.loads(path.read_text())
        return set(data.get("seen_ids", []))
    except Exception:
        return set()


def _save_seen(plugin_root: Path, seen: set) -> None:
    path = plugin_root / SEEN_FILE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"seen_ids": sorted(seen)}, indent=2))
    os.replace(tmp, path)


# ── network ────────────────────────────────────────────────────────────────────

def _fetch(url: str, version: str, timeout: float) -> Optional[Dict[str, Any]]:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", f"ainl-cortex/{version}")
    try:
        ctx = _ssl_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


# ── auto-update ────────────────────────────────────────────────────────────────

def _try_auto_update(plugin_root: Path, notif: Dict[str, Any], current_version: str) -> Optional[str]:
    """
    Runs `git pull --ff-only` inside plugin_root.
    Returns a human-readable result string, or None if skipped.
    """
    au = notif.get("auto_update")
    if not (isinstance(au, dict) and au.get("enabled")):
        return None
    if au.get("artifact") != PLUGIN_ARTIFACT:
        return None
    if not _version_in_range(current_version, au.get("min_version"), au.get("max_version")):
        return None

    try:
        r = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=str(plugin_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            return f"auto-updated ainl-cortex: {r.stdout.strip()[:200]}"
        else:
            return f"auto-update attempted but failed: {(r.stderr or r.stdout or '').strip()[:200]}"
    except Exception as e:
        return f"auto-update error: {e}"


# ── public API ─────────────────────────────────────────────────────────────────

def poll(plugin_root: Path, config: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Check the notifications feed and return:
      new_notifs  — list of notification dicts not yet seen (to show in banner)
      update_msgs — list of strings from any auto-update attempts

    Reads config["notifications"] for:
      enabled               (bool, default True)
      url                   (str, overrides NOTIFICATIONS_URL)
      check_timeout_seconds (float, default 5.0)
      auto_update           (bool, default False) — gate for running git pull
    """
    notif_cfg: Dict[str, Any] = config.get("notifications", {})
    if not notif_cfg.get("enabled", True):
        return [], []

    url = notif_cfg.get("url", NOTIFICATIONS_URL)
    timeout = float(notif_cfg.get("check_timeout_seconds", 5.0))
    auto_update_allowed = bool(notif_cfg.get("auto_update", False))

    current_version = _read_plugin_version(plugin_root)
    payload = _fetch(url, current_version, timeout)
    if payload is None:
        return [], []

    # 1. Schema version gate
    schema_v = payload.get("schema_version")
    if not isinstance(schema_v, (int, float)) or schema_v < 1:
        return [], []

    raw_notifs: List[Dict] = payload.get("notifications", [])
    if not isinstance(raw_notifs, list):
        return [], []

    now = datetime.now(tz=timezone.utc)

    # 2. Filter by targets
    targeted = [
        n for n in raw_notifs
        if isinstance(n, dict) and bool(OUR_TARGETS & set(n.get("targets", [])))
    ]

    # 3. Drop expired
    active = [
        n for n in targeted
        if not (_parse_dt(n.get("expires_at")) and now > _parse_dt(n["expires_at"]))
    ]

    # 4. Sort: priority desc (default 0), then published_at desc
    def _sort_key(n: Dict) -> Tuple:
        pri = n.get("priority", 0) or 0
        pub = _parse_dt(n.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc)
        return (-pri, -pub.timestamp())

    active.sort(key=_sort_key)

    # 5. Filter to unseen
    seen = _load_seen(plugin_root)
    new_notifs = [n for n in active if n.get("id") and n["id"] not in seen]

    if not new_notifs:
        return [], []

    # Mark all active IDs as seen (not just new ones — avoids re-surfacing expired→restored)
    for n in active:
        if n.get("id"):
            seen.add(n["id"])
    _save_seen(plugin_root, seen)

    # 6. Auto-update (only for new notifications that carry auto_update)
    update_msgs: List[str] = []
    if auto_update_allowed:
        for n in new_notifs:
            msg = _try_auto_update(plugin_root, n, current_version)
            if msg:
                update_msgs.append(msg)

    return new_notifs, update_msgs


# ── banner formatter ───────────────────────────────────────────────────────────

_SEVERITY_PREFIX = {
    "error": "🔴",
    "warning": "🟡",
    "info": "🔵",
}


def format_banner(new_notifs: List[Dict[str, Any]], update_msgs: List[str]) -> str:
    """Render a ━━━ NOTIFICATIONS ━━━ block for the SessionStart system message."""
    if not new_notifs and not update_msgs:
        return ""

    lines = ["\n━━━ AINL CORTEX NOTIFICATIONS ━━━"]
    for n in new_notifs:
        severity = n.get("severity", "info")
        prefix = _SEVERITY_PREFIX.get(severity, "🔵")
        title = n.get("title", "(no title)")
        body = n.get("body", "")
        action = n.get("action_url")
        lines.append(f"  {prefix} [{severity.upper()}] {title}")
        if body:
            lines.append(f"     {body}")
        if action:
            lines.append(f"     → {action}")

    for msg in update_msgs:
        lines.append(f"  ✅ {msg}")

    lines.append("━━━ END NOTIFICATIONS ━━━\n")
    return "\n".join(lines)
