"""
A2A bridge daemon lifecycle management.

Ensures armaraos_a2a_bridge.py is running as a background process.
Called from startup.py — must complete within 5 seconds.
"""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any

sys.path.insert(0, str(Path(__file__).parent))


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


def _wait_for_port(host: str, port: int, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(host, port, timeout=0.3):
            return True
        time.sleep(0.2)
    return False


def ensure_bridge_running(plugin_root: Path, config: dict) -> Dict[str, Any]:
    """
    Start the A2A bridge if not already running.
    Returns status dict consumed by startup.py banner.
    """
    a2a_cfg = config.get("a2a", {})
    if not a2a_cfg.get("enabled", True):
        return {"running": False, "reason": "disabled"}

    host = a2a_cfg.get("bridge_host", "127.0.0.1")
    port = int(a2a_cfg.get("bridge_port", 7860))
    bridge_script = a2a_cfg.get("bridge_script", "")
    pidfile = plugin_root / a2a_cfg.get("bridge_pidfile", "a2a/bridge.pid")
    logfile = plugin_root / a2a_cfg.get("bridge_logfile", "a2a/logs/bridge.log")

    if not bridge_script or not Path(bridge_script).exists():
        return {"running": False, "reason": f"bridge_script not found: {bridge_script}"}

    # Check if already running
    if pidfile.exists():
        try:
            pid = int(pidfile.read_text().strip())
            if _pid_alive(pid) and _port_open(host, port):
                return {"running": True, "pid": pid, "port": port}
        except Exception:
            pass

    # Launch bridge
    try:
        inbox_writer = plugin_root / "hooks" / "a2a_inbox_writer.py"
        python_bin = plugin_root / ".venv" / "bin" / "python"
        if not python_bin.exists():
            python_bin = Path(sys.executable)

        bridge_cmd = f"{python_bin} {inbox_writer}"

        env = os.environ.copy()
        env["HERMES_AINL_BRIDGE_PORT"] = str(port)
        env["HERMES_AINL_BRIDGE_HOST"] = host
        env["HERMES_AINL_BRIDGE_QUIET"] = "1"
        env["HERMES_AINL_BRIDGE_CMD"] = bridge_cmd
        env["AINL_PLUGIN_ROOT"] = str(plugin_root)

        logfile.parent.mkdir(parents=True, exist_ok=True)
        log_fd = open(logfile, "a")

        proc = subprocess.Popen(
            [sys.executable, bridge_script],
            stdout=log_fd,
            stderr=log_fd,
            env=env,
            start_new_session=True,
        )

        pidfile.parent.mkdir(parents=True, exist_ok=True)
        pidfile.write_text(str(proc.pid))

        if _wait_for_port(host, port, timeout=2.0):
            return {"running": True, "pid": proc.pid, "port": port, "started": True}
        else:
            return {"running": False, "pid": proc.pid, "reason": "port not open after 2s"}

    except Exception as e:
        return {"running": False, "reason": str(e)}
