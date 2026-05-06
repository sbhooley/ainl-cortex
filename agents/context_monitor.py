#!/usr/bin/env python3
"""
Context Monitor Agent

Watches file paths and HTTP health endpoints defined in
a2a/monitors/monitor_configs.json. When a condition triggers:
  1. POSTs a notification to the local A2A bridge (if running)
  2. Appends the trigger to a2a/monitors/recent_triggers.json (fallback)

Run once (cron / launchd / loop):
  python3 agents/context_monitor.py [--plugin-root /path/to/plugin]

Or run as a daemon:
  python3 agents/context_monitor.py --daemon --interval 60
"""

import argparse
import json
import os
import socket
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── helpers ──────────────────────────────────────────────────────────────────

def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _atomic_write(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((host, port))
        s.close()
        return result == 0
    except Exception:
        return False


def _post_json(url: str, payload: dict, timeout: float = 3.0) -> Optional[dict]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _http_check(url: str, timeout: float = 5.0) -> Dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"ok": True, "status": resp.status}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "error": str(e)}
    except Exception as e:
        return {"ok": False, "status": 0, "error": str(e)}


# ── condition evaluators ──────────────────────────────────────────────────────

def _eval_file_condition(path_str: str, condition: str, state: dict) -> Optional[str]:
    """
    Evaluate a file-based condition.
    Returns a human-readable trigger message or None if not triggered.
    """
    p = Path(path_str)
    key = f"mtime:{path_str}"

    if condition == "file_changed":
        try:
            mtime = p.stat().st_mtime
            prev = state.get(key)
            state[key] = mtime
            if prev is not None and mtime != prev:
                return f"file_changed: {path_str}"
        except FileNotFoundError:
            pass

    elif condition == "file_created":
        exists = p.exists()
        prev = state.get(f"exists:{path_str}", False)
        state[f"exists:{path_str}"] = exists
        if exists and not prev:
            return f"file_created: {path_str}"

    elif condition == "file_deleted":
        exists = p.exists()
        prev = state.get(f"exists:{path_str}", True)
        state[f"exists:{path_str}"] = exists
        if not exists and prev:
            return f"file_deleted: {path_str}"

    elif condition == "file_size_exceeds":
        # path_str may contain a threshold suffix like "/some/file:1048576"
        parts = path_str.rsplit(":", 1)
        fpath = parts[0]
        threshold = int(parts[1]) if len(parts) == 2 else 10_485_760
        try:
            size = Path(fpath).stat().st_size
            if size > threshold:
                return f"file_size_exceeds: {fpath} ({size} bytes > {threshold})"
        except FileNotFoundError:
            pass

    return None


def _eval_http_condition(url: str, condition: str) -> Optional[str]:
    """
    Evaluate an HTTP-based condition.
    Returns a trigger message or None.
    """
    result = _http_check(url)

    if condition == "http_error" and not result["ok"]:
        return f"http_error: {url} → status {result['status']}"
    elif condition == "http_down" and result["status"] == 0:
        return f"http_down: {url} unreachable"
    elif condition == "http_ok" and result["ok"]:
        return f"http_ok: {url} → {result['status']}"

    return None


# ── main monitor logic ────────────────────────────────────────────────────────

def run_monitors(plugin_root: Path, state: dict) -> List[Dict[str, Any]]:
    """
    Run all configured monitors once. Return list of triggered events.
    """
    configs_path = plugin_root / "a2a" / "monitors" / "monitor_configs.json"
    monitors = _read_json(configs_path, [])
    if not monitors:
        return []

    triggered = []
    for mon in monitors:
        paths = mon.get("paths", [])
        conditions = mon.get("conditions", [])
        template = mon.get("notify_message", "Monitor triggered: {condition}")
        mon_id = mon.get("id", "unknown")

        for condition in conditions:
            for path_str in paths:
                msg = None

                # Determine if it's a URL or file path
                if path_str.startswith(("http://", "https://")):
                    msg = _eval_http_condition(path_str, condition)
                else:
                    msg = _eval_file_condition(path_str, condition, state)

                if msg:
                    human_msg = template.format(condition=msg)
                    triggered.append({
                        "monitor_id": mon_id,
                        "condition": condition,
                        "path": path_str,
                        "message": human_msg,
                        "triggered_at": int(time.time()),
                    })

    return triggered


def dispatch_triggers(
    plugin_root: Path,
    triggers: List[Dict[str, Any]],
    bridge_host: str,
    bridge_port: int,
) -> None:
    """
    For each trigger:
    - POST to bridge if alive
    - Always append to recent_triggers.json for startup.py pickup
    """
    if not triggers:
        return

    bridge_alive = _port_open(bridge_host, bridge_port)
    bridge_url = f"http://{bridge_host}:{bridge_port}"

    triggers_file = plugin_root / "a2a" / "monitors" / "recent_triggers.json"
    existing = _read_json(triggers_file, [])

    for trig in triggers:
        msg_text = (
            f"X-From-Agent: context-monitor\n"
            f"X-Urgency: normal\n"
            f"{trig['message']}"
        )

        if bridge_alive:
            _post_json(
                f"{bridge_url}/tasks/send",
                {"message": {"parts": [{"type": "text", "text": msg_text}]}},
            )

        existing.append(trig)

    # Keep only the last 50 triggers
    _atomic_write(triggers_file, existing[-50:])


def load_state(state_file: Path) -> dict:
    return _read_json(state_file, {})


def save_state(state_file: Path, state: dict) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(state_file, state)


def main():
    parser = argparse.ArgumentParser(description="AINL A2A Context Monitor")
    parser.add_argument("--plugin-root", default=None, help="Plugin root directory")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon loop")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval in seconds (daemon mode)")
    args = parser.parse_args()

    if args.plugin_root:
        plugin_root = Path(args.plugin_root).resolve()
    else:
        env_root = os.environ.get("AINL_PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT")
        plugin_root = Path(env_root).resolve() if env_root else Path(__file__).resolve().parent.parent

    # Load bridge config
    cfg = _read_json(plugin_root / "config.json", {})
    a2a_cfg = cfg.get("a2a", {})
    bridge_host = a2a_cfg.get("bridge_host", "127.0.0.1")
    bridge_port = int(a2a_cfg.get("bridge_port", 7860))

    state_file = plugin_root / "a2a" / "monitors" / "monitor_state.json"
    state = load_state(state_file)

    if args.daemon:
        while True:
            try:
                triggers = run_monitors(plugin_root, state)
                dispatch_triggers(plugin_root, triggers, bridge_host, bridge_port)
                save_state(state_file, state)
            except Exception as e:
                print(f"[context_monitor] error: {e}", file=sys.stderr)
            time.sleep(args.interval)
    else:
        triggers = run_monitors(plugin_root, state)
        dispatch_triggers(plugin_root, triggers, bridge_host, bridge_port)
        save_state(state_file, state)
        if triggers:
            print(json.dumps({"triggered": len(triggers), "events": triggers}, indent=2))
        else:
            print(json.dumps({"triggered": 0}))


if __name__ == "__main__":
    main()
