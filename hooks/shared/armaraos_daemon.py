"""ArmaraOS daemon discovery helpers (shared by A2A hooks and MCP tools)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

DAEMON_URL_CACHE_NAME = "armaraos_daemon_url.json"
LEGACY_DAEMON_URL_CACHE_NAME = "openfang_url.json"

DAEMON_NOT_FOUND_REASON = (
    "ArmaraOS daemon not found — start ArmaraOS to enable A2A"
)
DAEMON_NOT_FOUND_ERROR = (
    "ArmaraOS daemon not found — is the daemon running?"
)

# Legacy `openfang` binary names may still appear in lsof until fully renamed.
_LSOF_PROCESS_MARKERS = ("armaraos", "openfang")


def daemon_url_cache_path(plugin_root: Path) -> Path:
    return plugin_root / "a2a" / DAEMON_URL_CACHE_NAME


def resolve_daemon_cache_file(
    cache_file: Optional[str],
    plugin_root: Optional[Path] = None,
) -> Optional[str]:
    """Prefer armaraos_daemon_url.json; fall back to legacy openfang_url.json."""
    if cache_file:
        path = Path(cache_file)
        if path.is_file():
            return str(path)
        legacy = path.parent / LEGACY_DAEMON_URL_CACHE_NAME
        if legacy.is_file():
            return str(legacy)
        return str(path)
    if plugin_root is None:
        return None
    a2a = plugin_root / "a2a"
    primary = a2a / DAEMON_URL_CACHE_NAME
    if primary.is_file():
        return str(primary)
    legacy = a2a / LEGACY_DAEMON_URL_CACHE_NAME
    if legacy.is_file():
        return str(legacy)
    return str(primary)


def _scan_daemon_listen_port_windows() -> Tuple[Optional[str], Optional[int]]:
    """Windows fallback: use netstat + tasklist to find the daemon listen port."""
    try:
        r = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5,
        )
        # Parse: Proto  Local Address  Foreign Address  State  PID
        listening_pids: Dict[int, Tuple[str, int]] = {}
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5 or "LISTENING" not in parts[3]:
                continue
            if not parts[0].upper().startswith("TCP"):
                continue
            try:
                pid = int(parts[4])
                host, _, port_str = parts[1].rpartition(":")
                # Normalise wildcard bind addresses to loopback
                if host in ("0.0.0.0", "::", "[::]", ""):
                    host = "127.0.0.1"
                if pid not in listening_pids:
                    listening_pids[pid] = (host, int(port_str))
            except (ValueError, IndexError):
                pass

        if not listening_pids:
            return None, None

        t = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5,
        )
        for line in t.stdout.splitlines():
            lower = line.lower()
            if not any(marker in lower for marker in _LSOF_PROCESS_MARKERS):
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                try:
                    pid = int(parts[1].strip().strip('"'))
                    if pid in listening_pids:
                        return listening_pids[pid]
                except ValueError:
                    pass
    except Exception:
        pass
    return None, None


def scan_daemon_listen_port() -> Tuple[Optional[str], Optional[int]]:
    """Scan for a listening ArmaraOS daemon. Returns (host, port) or (None, None)."""
    if sys.platform == "win32":
        return _scan_daemon_listen_port_windows()
    try:
        r = subprocess.run(
            ["lsof", "-iTCP", "-sTCP:LISTEN", "-n", "-P"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in r.stdout.splitlines():
            lower = line.lower()
            if not any(marker in lower for marker in _LSOF_PROCESS_MARKERS):
                continue
            for part in line.split():
                if ":" in part:
                    host, _, port_str = part.rpartition(":")
                    try:
                        return host or "127.0.0.1", int(port_str)
                    except ValueError:
                        pass
    except Exception:
        pass
    return None, None


def scan_daemon_listen_port_int() -> Optional[int]:
    """Return listen port only (127.0.0.1 assumed)."""
    _, port = scan_daemon_listen_port()
    return port


def fetch_daemon_cost_hint(base_url: str, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
    """Optional ArmaraOS usage/eco line for SessionStart (graceful None on failure)."""
    import json
    import urllib.request

    try:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/api/usage/summary", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        eco = data.get("eco") or data.get("compression") or {}
        saved = eco.get("tokens_saved") or eco.get("total_tokens_saved")
        if saved:
            return {"tokens_saved": int(saved), "source": "daemon"}
        return {"reachable": True, "source": "daemon"}
    except Exception:
        return None
