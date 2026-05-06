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
import time
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


def _scan_openfang_port() -> Optional[int]:
    """Scan lsof output for a listening openfang process and return its port."""
    import subprocess
    try:
        r = subprocess.run(
            ["lsof", "-iTCP", "-sTCP:LISTEN", "-n", "-P"],
            capture_output=True, text=True, timeout=5
        )
        for line in r.stdout.splitlines():
            if "openfang" in line.lower():
                # e.g. "openfang-  1234 ...  TCP 127.0.0.1:63557 (LISTEN)"
                parts = line.split()
                for p in parts:
                    if ":" in p and "(LISTEN)" not in p:
                        try:
                            return int(p.rsplit(":", 1)[1])
                        except ValueError:
                            pass
    except Exception:
        pass
    return None


_URL_CACHE_TTL = 1800  # 30 minutes


def discover_daemon(
    daemon_json_path: Optional[str] = None,
    cache_file: Optional[str] = None,
) -> Tuple[Optional[str], Optional[int]]:
    """
    Discover the ArmaraOS daemon URL and PID.

    Strategy (fastest first):
    1. Plugin-local cache (a2a/openfang_url.json) written by startup hook — valid 30 min
    2. daemon.json recorded listen_addr — check if port is still open
    3. lsof scan for live openfang process (dynamic port on restart)
    """
    # ── 1. Plugin-local cache ─────────────────────────────────────────────────
    if cache_file:
        try:
            cache = json.loads(Path(cache_file).read_text())
            age = time.time() - cache.get("discovered_at", 0)
            if age < _URL_CACHE_TTL:
                base_url = cache.get("base_url", "")
                pid = cache.get("pid")
                if base_url:
                    # Quick TCP probe to confirm still alive
                    host, _, port_str = base_url.rstrip("/").rpartition(":")
                    host = host.replace("http://", "")
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(0.5)
                        if s.connect_ex((host, int(port_str))) == 0:
                            s.close()
                            return base_url, pid
                        s.close()
                    except Exception:
                        pass
        except Exception:
            pass

    # ── 2. daemon.json ────────────────────────────────────────────────────────
    d = _read_daemon_json(daemon_json_path)
    pid = d.get("pid") if d else None
    if d:
        listen = d.get("listen_addr", "")
        if listen:
            host, _, port_str = listen.rpartition(":")
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.0)
                reachable = s.connect_ex((host, int(port_str))) == 0
                s.close()
                if reachable:
                    return f"http://{listen}", pid
            except Exception:
                pass

    # ── 3. lsof scan ─────────────────────────────────────────────────────────
    live_port = _scan_openfang_port()
    if live_port:
        return f"http://127.0.0.1:{live_port}", pid

    return None, pid


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
    cache_file: Optional[str] = None,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """
    Send a message to a specific ArmaraOS agent by UUID.
    Uses POST /api/agents/{id}/message which returns {"response": "...", ...}.
    """
    daemon_url, _ = discover_daemon(daemon_json_path, cache_file=cache_file)
    if not daemon_url:
        return {"error": "ArmaraOS daemon not found — is openfang running?", "reachable": False}
    result = _post_json(
        f"{daemon_url}/api/agents/{agent_id}/message",
        {"message": message_text},
        timeout,
    )
    # Normalise: expose reply as top-level "response" field
    if "response" not in result and "error" not in result:
        # Fallback: extract from messages array if present
        for msg in result.get("messages", []):
            if msg.get("role") == "agent":
                parts = msg.get("parts", [])
                result["response"] = " ".join(p.get("text", "") for p in parts)
                break
    return result


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
    cache_file: Optional[str] = None,
    timeout: float = 3.0,
) -> Dict[str, Any]:
    """List agents available via the ArmaraOS A2A protocol."""
    daemon_url, _ = discover_daemon(daemon_json_path, cache_file=cache_file)
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
