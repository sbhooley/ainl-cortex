"""
ArmaraOS daemon discovery for the A2A subsystem.

Replaces the old "launch a Python bridge" approach.
ArmaraOS is the A2A bridge — we just discover it via ~/.armaraos/daemon.json.
"""

import json
import os
import socket
import time
from pathlib import Path
from typing import Dict, Any


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((host, port))
        s.close()
        return result == 0
    except Exception:
        return False


def _scan_openfang_port() -> tuple:
    """Scan lsof for a listening openfang process. Returns (host, port) or (None, None)."""
    import subprocess
    try:
        r = subprocess.run(
            ["lsof", "-iTCP", "-sTCP:LISTEN", "-n", "-P"],
            capture_output=True, text=True, timeout=5
        )
        for line in r.stdout.splitlines():
            if "openfang" in line.lower():
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


def _write_url_cache(plugin_root: Path, base_url: str, pid, version: str) -> None:
    """Write discovered daemon URL to plugin-local cache for fast reuse."""
    cache_file = plugin_root / "a2a" / "openfang_url.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_file.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "base_url": base_url,
        "pid": pid,
        "version": version,
        "discovered_at": int(time.time()),
    }))
    os.replace(tmp, cache_file)


def ensure_bridge_running(plugin_root: Path, config: dict) -> Dict[str, Any]:
    """
    Discover the ArmaraOS daemon, cache its URL, and return its status.

    Discovery order:
      1. daemon.json — check if the recorded port is still alive
      2. lsof scan   — openfang uses dynamic ports on restart
    Result is written to a2a/openfang_url.json so tools skip re-scanning.
    """
    a2a_cfg = config.get("a2a", {})
    if not a2a_cfg.get("enabled", True):
        return {"running": False, "reason": "disabled"}

    daemon_json_path = Path(
        a2a_cfg.get("daemon_json", "~/.armaraos/daemon.json")
    ).expanduser()

    pid = None
    version = "unknown"

    # ── Step 1: try daemon.json ───────────────────────────────────────────────
    if daemon_json_path.exists():
        try:
            daemon = json.loads(daemon_json_path.read_text())
            pid = daemon.get("pid")
            version = daemon.get("version", "unknown")
            listen_addr = daemon.get("listen_addr", "")
            if listen_addr:
                host, _, port_str = listen_addr.rpartition(":")
                port = int(port_str)
                if _pid_alive(pid) and _port_open(host, port):
                    base_url = f"http://{listen_addr}"
                    _write_url_cache(plugin_root, base_url, pid, version)
                    return {"running": True, "pid": pid, "port": port, "host": host,
                            "base_url": base_url, "version": version, "source": "daemon.json"}
        except Exception:
            pass

    # ── Step 2: lsof scan for dynamic port ───────────────────────────────────
    host, port = _scan_openfang_port()
    if host and port:
        base_url = f"http://{host}:{port}"
        # Confirm it's actually the ArmaraOS API
        try:
            import urllib.request
            resp = urllib.request.urlopen(f"{base_url}/api/health", timeout=2)
            data = json.loads(resp.read())
            version = data.get("version", version)
            # Try to get PID from /api/health or keep what we have from daemon.json
        except Exception:
            pass
        _write_url_cache(plugin_root, base_url, pid, version)
        return {"running": True, "pid": pid, "port": port, "host": host,
                "base_url": base_url, "version": version, "source": "lsof"}

    # ── Not found ─────────────────────────────────────────────────────────────
    # Clear stale cache so tools don't use a dead URL
    cache_file = plugin_root / "a2a" / "openfang_url.json"
    if cache_file.exists():
        cache_file.unlink(missing_ok=True)

    return {"running": False, "reason": "openfang not found — start ArmaraOS to enable A2A"}
