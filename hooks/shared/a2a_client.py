"""
Stdlib-only HTTP client for the ArmaraOS daemon A2A API.

Discovers the daemon via ~/.armaraos/daemon.json.
No requests, no venv dependency — safe to call from any hook.

ArmaraOS native endpoints used:
  GET  /api/health
  GET  /.well-known/agent.json
  GET  /a2a/agents
  POST /a2a/tasks/send   {"agent_id": "...", "message": {"role": "user", "parts": [{"text": "..."}]}}
  GET  /a2a/tasks/{id}
"""

import json
import os
import socket
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


_DEFAULT_DAEMON_JSON = Path.home() / ".armaraos" / "daemon.json"


def _read_daemon_json(daemon_json_path: Optional[str] = None) -> Optional[Dict]:
    path = Path(daemon_json_path).expanduser() if daemon_json_path else _DEFAULT_DAEMON_JSON
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def discover_daemon(daemon_json_path: Optional[str] = None) -> Tuple[Optional[str], Optional[int]]:
    """
    Read ~/.armaraos/daemon.json and return (base_url, pid).
    Returns (None, None) if daemon.json doesn't exist or is unreadable.
    """
    d = _read_daemon_json(daemon_json_path)
    if not d:
        return None, None
    listen = d.get("listen_addr", "")
    if not listen:
        return None, None
    return f"http://{listen}", d.get("pid")


def _get_json(url: str, timeout: float) -> Dict[str, Any]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "reachable": True}
    except urllib.error.URLError as e:
        return {"error": str(e.reason), "reachable": False}
    except Exception as e:
        return {"error": str(e), "reachable": False}


def _post_json(url: str, payload: dict, timeout: float) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "reachable": True}
    except urllib.error.URLError as e:
        return {"error": str(e.reason), "reachable": False}
    except Exception as e:
        return {"error": str(e), "reachable": False}


def is_bridge_alive(
    host: str = "127.0.0.1",
    port: int = 50051,
    daemon_json_path: Optional[str] = None,
    timeout: float = 1.5,
) -> bool:
    """Check if the ArmaraOS daemon is reachable. host/port are ignored if daemon.json resolves."""
    base_url, _ = discover_daemon(daemon_json_path)
    if base_url:
        result = _get_json(f"{base_url}/api/health", timeout=timeout)
        return "error" not in result
    # Fallback: TCP probe on provided host/port
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        ok = s.connect_ex((host, port)) == 0
        s.close()
        return ok
    except Exception:
        return False


def post_a2a(
    base_url: str,
    method: str,
    params: dict,
    timeout: float = 5.0,
    daemon_json_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send to an ArmaraOS agent via POST /a2a/tasks/send.

    `base_url` is ignored — the daemon URL is always resolved from daemon.json.
    `method` is ignored (kept for backward-compat call sites).
    `params` must contain {"message": {"parts": [{"type": "text", "text": "..."}]}}
    and optionally "agent_id".
    """
    daemon_url, _ = discover_daemon(daemon_json_path)
    if not daemon_url:
        return {"error": "ArmaraOS daemon not found. Is armaraos running?", "reachable": False}

    # Extract message text from the params
    parts = params.get("message", {}).get("parts", [])
    text = " ".join(p.get("text", "") for p in parts if p.get("type") == "text")
    agent_id = params.get("agent_id", "")

    payload: Dict[str, Any] = {
        "message": {
            "role": "user",
            "parts": [{"text": text}],
        }
    }
    if agent_id:
        payload["agent_id"] = agent_id

    return _post_json(f"{daemon_url}/a2a/tasks/send", payload, timeout)


def send_to_agent(
    agent_id: str,
    message_text: str,
    daemon_json_path: Optional[str] = None,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """Send a message to a specific ArmaraOS agent by ID."""
    daemon_url, _ = discover_daemon(daemon_json_path)
    if not daemon_url:
        return {"error": "ArmaraOS daemon not found", "reachable": False}
    payload = {
        "agent_id": agent_id,
        "message": {"role": "user", "parts": [{"text": message_text}]},
    }
    return _post_json(f"{daemon_url}/a2a/tasks/send", payload, timeout)


def get_task_status(
    task_id: str,
    daemon_json_path: Optional[str] = None,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """Get status of an A2A task by ID from ArmaraOS."""
    daemon_url, _ = discover_daemon(daemon_json_path)
    if not daemon_url:
        return {"error": "ArmaraOS daemon not found", "reachable": False}
    return _get_json(f"{daemon_url}/a2a/tasks/{task_id}", timeout=timeout)


def list_a2a_agents(
    daemon_json_path: Optional[str] = None,
    timeout: float = 3.0,
) -> Dict[str, Any]:
    """List agents available via the ArmaraOS A2A protocol."""
    daemon_url, _ = discover_daemon(daemon_json_path)
    if not daemon_url:
        return {"error": "ArmaraOS daemon not found", "reachable": False}
    return _get_json(f"{daemon_url}/a2a/agents", timeout=timeout)


def get_agent_card(
    base_url: str = "",
    timeout: float = 3.0,
    daemon_json_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch /.well-known/agent.json from the ArmaraOS daemon."""
    daemon_url, _ = discover_daemon(daemon_json_path)
    target = (daemon_url or base_url).rstrip("/")
    if not target:
        return {"error": "No daemon URL available"}
    return _get_json(f"{target}/.well-known/agent.json", timeout=timeout)
