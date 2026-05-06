"""
ArmaraOS daemon discovery for the A2A subsystem.

Replaces the old "launch a Python bridge" approach.
ArmaraOS is the A2A bridge — we just discover it via ~/.armaraos/daemon.json.
"""

import json
import os
import socket
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


def ensure_bridge_running(plugin_root: Path, config: dict) -> Dict[str, Any]:
    """
    Discover the ArmaraOS daemon and return its status.
    No bridge process is launched — ArmaraOS IS the bridge.
    """
    a2a_cfg = config.get("a2a", {})
    if not a2a_cfg.get("enabled", True):
        return {"running": False, "reason": "disabled"}

    daemon_json_path = Path(
        a2a_cfg.get("daemon_json", "~/.armaraos/daemon.json")
    ).expanduser()

    if not daemon_json_path.exists():
        return {
            "running": False,
            "reason": f"daemon.json not found at {daemon_json_path} — is ArmaraOS installed?",
        }

    try:
        daemon = json.loads(daemon_json_path.read_text())
    except Exception as e:
        return {"running": False, "reason": f"could not read daemon.json: {e}"}

    listen_addr = daemon.get("listen_addr", "")
    pid = daemon.get("pid")
    version = daemon.get("version", "unknown")

    if not listen_addr:
        return {"running": False, "reason": "daemon.json has no listen_addr"}

    host, _, port_str = listen_addr.rpartition(":")
    try:
        port = int(port_str)
    except ValueError:
        return {"running": False, "reason": f"invalid listen_addr: {listen_addr}"}

    pid_alive = _pid_alive(pid) if pid else False
    port_ok = _port_open(host, port, timeout=1.0)

    if pid_alive and port_ok:
        return {
            "running": True,
            "pid": pid,
            "port": port,
            "host": host,
            "base_url": f"http://{listen_addr}",
            "version": version,
        }

    reason_parts = []
    if not pid_alive:
        reason_parts.append(f"pid {pid} not alive")
    if not port_ok:
        reason_parts.append(f"port {port} not open")

    return {
        "running": False,
        "pid": pid,
        "port": port,
        "host": host,
        "base_url": f"http://{listen_addr}",
        "version": version,
        "reason": "; ".join(reason_parts) + " — start ArmaraOS to enable A2A",
    }
