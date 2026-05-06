"""
Stdlib-only HTTP client for the local A2A bridge.

No requests, no venv dependency — safe to call from any hook.
"""

import json
import socket
import urllib.request
import urllib.error
from typing import Any, Dict


def is_bridge_alive(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((host, port))
        s.close()
        return result == 0
    except Exception:
        return False


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


def post_a2a(
    base_url: str,
    method: str,
    params: dict,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """Send JSON-RPC 2.0 to /a2a endpoint."""
    url = base_url.rstrip("/") + "/a2a"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    return _post_json(url, payload, timeout)


def post_message_send(
    base_url: str,
    message: str,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """Send A2A HTTP binding message to /message:send."""
    url = base_url.rstrip("/") + "/message:send"
    payload = {
        "message": {
            "parts": [{"type": "text", "text": message}]
        }
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/a2a+json"},
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


def get_agent_card(base_url: str, timeout: float = 3.0) -> Dict[str, Any]:
    """Fetch /.well-known/agent.json from an A2A agent."""
    url = base_url.rstrip("/") + "/.well-known/agent.json"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e), "reachable": False}
