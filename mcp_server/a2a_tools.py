"""
A2A MCP tool implementations using the ArmaraOS native A2A API.

Provides 7 tools: a2a_send, a2a_list_agents, a2a_register_agent,
a2a_note_to_self, a2a_register_monitor, a2a_task_send, a2a_task_status.

ArmaraOS is the A2A bridge. The daemon URL is discovered from
~/.armaraos/daemon.json at runtime.
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

try:
    from .a2a_store import (
        store_message_node,
        store_task_episode,
        store_thread_summary,
        query_thread_history,
    )
    from .graph_store import GraphStore
except ImportError:
    from a2a_store import (
        store_message_node,
        store_task_episode,
        store_thread_summary,
        query_thread_history,
    )
    from graph_store import GraphStore

# Lazy imports of hook-side stdlib utilities (no venv needed)
def _a2a_log():
    from shared.a2a_log import append_log
    return append_log

def _a2a_inbox():
    from shared.a2a_inbox import write_self_note
    return write_self_note

def _a2a_client():
    from shared.a2a_client import (
        send_to_agent, list_a2a_agents, get_agent_card,
        is_bridge_alive, get_task_status, discover_daemon,
    )
    return send_to_agent, list_a2a_agents, get_agent_card, is_bridge_alive, get_task_status, discover_daemon

def _send(agent_id: str, text: str, daemon_json: str, cache: str, timeout: float = 60.0):
    send_to_agent, *_ = _a2a_client()
    return send_to_agent(agent_id, text, daemon_json_path=daemon_json, cache_file=cache, timeout=timeout)


def _atomic_write(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


class A2ATools:
    def __init__(self, plugin_root: Path, store: GraphStore, project_id: str, config: dict):
        self.plugin_root = plugin_root
        self.store = store
        self.project_id = project_id
        self.cfg = config.get("a2a", {})
        self.daemon_json = self.cfg.get("daemon_json", "~/.armaraos/daemon.json")
        self.daemon_cache = str(plugin_root / "a2a" / "openfang_url.json")
        self.registry_path = plugin_root / "a2a" / "agents" / "registry.json"
        self.tasks_dir = plugin_root / "a2a" / "tasks"
        self.monitors_path = plugin_root / "a2a" / "monitors" / "monitor_configs.json"

    def _registry(self) -> dict:
        data = _read_json(self.registry_path, {})
        # Migrate list format (old default) to dict keyed by name
        if isinstance(data, list):
            return {entry["name"]: entry for entry in data if "name" in entry}
        return data

    def _save_registry(self, reg: dict) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.registry_path, reg)

    def _daemon_alive(self) -> bool:
        _, _, _, is_bridge_alive, _, _ = _a2a_client()
        return is_bridge_alive(daemon_json_path=self.daemon_json)

    def _daemon_url(self) -> Optional[str]:
        _, _, _, _, _, discover_daemon = _a2a_client()
        base_url, _ = discover_daemon(self.daemon_json, cache_file=self.daemon_cache)
        return base_url

    # ── a2a_send ──────────────────────────────────────────────────────────────

    def a2a_send(
        self,
        to: str,
        message: str,
        thread_id: Optional[str] = None,
        urgency: str = "normal",
    ) -> Dict[str, Any]:
        reg = self._registry()
        if to not in reg:
            return {
                "error": f"Agent '{to}' not registered. Use a2a_register_agent first.",
                "registered_agents": list(reg.keys()),
            }

        agent = reg[to]
        agent_id = agent.get("agent_id") or agent.get("armaraos_id")
        tid = thread_id or str(uuid.uuid4())

        full_text = (
            f"X-From-Agent: claude-code\n"
            f"X-Thread-Id: {tid}\n"
            f"X-Urgency: {urgency}\n"
            f"{message}"
        )

        result = _send(agent_id or to, full_text, self.daemon_json, self.daemon_cache, timeout=60.0)

        if result.get("error"):
            _a2a_log()(self.plugin_root, "OUT", "claude-code", to, tid, urgency, message[:120], status="fail")
            return {"sent": False, "error": result["error"], "thread_id": tid}

        store_message_node(self.store, self.project_id, "outbound", "claude-code", to, tid, urgency, message)
        _a2a_log()(self.plugin_root, "OUT", "claude-code", to, tid, urgency, message[:120])

        # Store reply as inbound message node
        reply = result.get("response", "")
        if reply:
            store_message_node(self.store, self.project_id, "inbound", to, "claude-code", tid, urgency, reply)
            _a2a_log()(self.plugin_root, "IN", to, "claude-code", tid, urgency, reply[:120])

        reg[to]["last_seen_at"] = int(time.time())
        self._save_registry(reg)

        out = {"sent": True, "to": to, "thread_id": tid, "urgency": urgency}
        if reply:
            out["reply"] = reply
        return out

    # ── a2a_list_agents ───────────────────────────────────────────────────────

    def a2a_list_agents(self) -> Dict[str, Any]:
        reg = self._registry()
        _, list_armaraos_agents, _, _, _, _ = _a2a_client()

        daemon_url = self._daemon_url()
        daemon_running = daemon_url is not None

        # Fetch live agent list from ArmaraOS
        armaraos_agents = {}
        if daemon_running:
            result = list_armaraos_agents(daemon_json_path=self.daemon_json, cache_file=self.daemon_cache, timeout=3.0)
            for ag in result.get("agents", []):
                armaraos_agents[ag.get("name", ag.get("id", ""))] = ag

        # Merge with local registry
        agents = []
        seen = set()
        for name, info in reg.items():
            entry = dict(info)
            live = armaraos_agents.get(name) or armaraos_agents.get(info.get("agent_id", ""))
            entry["reachable"] = live is not None
            if live:
                entry["agent_id"] = live.get("id", info.get("agent_id"))
                entry["capabilities"] = live.get("skills", info.get("capabilities", []))
            agents.append(entry)
            seen.add(name)

        # Add ArmaraOS agents not in local registry
        for name, ag in armaraos_agents.items():
            if name not in seen:
                agents.append({
                    "name": name,
                    "agent_id": ag.get("id"),
                    "description": ag.get("description", ""),
                    "capabilities": ag.get("skills", []),
                    "reachable": True,
                    "registered_at": None,
                    "last_seen_at": None,
                })

        return {
            "agents": agents,
            "count": len(agents),
            "daemon_running": daemon_running,
            "daemon_url": daemon_url,
        }

    # ── a2a_register_agent ────────────────────────────────────────────────────

    def a2a_register_agent(
        self,
        name: str,
        url: str = "",
        description: str = "",
        capabilities: Optional[list] = None,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        # url is optional now — agents are identified by agent_id in ArmaraOS
        if url and not url.startswith(("http://", "https://")):
            return {"error": "url must start with http:// or https://"}

        # If no agent_id supplied, try to discover it from ArmaraOS by name
        if not agent_id:
            _, list_armaraos_agents, _, _, _, _ = _a2a_client()
            result = list_armaraos_agents(daemon_json_path=self.daemon_json, timeout=3.0)
            for ag in result.get("agents", []):
                if ag.get("name", "").lower() == name.lower():
                    agent_id = ag.get("id")
                    if not description:
                        description = ag.get("description", "")
                    if not capabilities:
                        capabilities = ag.get("skills", [])
                    break

        reg = self._registry()
        reg[name] = {
            "name": name,
            "agent_id": agent_id,
            "url": url,
            "description": description,
            "capabilities": capabilities or [],
            "registered_at": int(time.time()),
            "last_seen_at": None,
        }
        self._save_registry(reg)
        return {"registered": True, "name": name, "agent_id": agent_id, "url": url or None}

    # ── a2a_note_to_self ──────────────────────────────────────────────────────

    def a2a_note_to_self(
        self,
        message: str,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        write_self_note = _a2a_inbox()
        urgency = self.cfg.get("self_inbox_urgency", "critical")
        note_id = write_self_note(
            self.plugin_root,
            message=message,
            context=context or "",
            urgency=urgency,
            tool_count=0,
        )
        store_message_node(
            self.store, self.project_id,
            "outbound", "self", "self",
            None, urgency, message,
        )
        return {"written": True, "id": note_id, "urgency": urgency}

    # ── a2a_register_monitor ──────────────────────────────────────────────────

    def a2a_register_monitor(
        self,
        paths: list,
        conditions: list,
        notify_message: str = "Monitor triggered: {condition}",
    ) -> Dict[str, Any]:
        self.monitors_path.parent.mkdir(parents=True, exist_ok=True)
        monitors = _read_json(self.monitors_path, [])
        monitor_id = str(uuid.uuid4())
        monitors.append({
            "id": monitor_id,
            "paths": paths,
            "conditions": conditions,
            "notify_message": notify_message,
            "registered_at": int(time.time()),
        })
        _atomic_write(self.monitors_path, monitors)
        return {"registered": True, "id": monitor_id, "conditions": len(conditions)}

    # ── a2a_task_send ─────────────────────────────────────────────────────────

    def a2a_task_send(
        self,
        to: str,
        task_description: str,
        callback_urgency: str = "normal",
    ) -> Dict[str, Any]:
        reg = self._registry()
        if to not in reg:
            return {"error": f"Agent '{to}' not registered. Use a2a_register_agent first."}

        task_id = str(uuid.uuid4())
        agent_id = reg[to].get("agent_id") or to

        full_text = (
            f"X-From-Agent: claude-code\n"
            f"X-Task-Id: {task_id}\n"
            f"X-Urgency: {callback_urgency}\n"
            f"{task_description}"
        )

        result = _send(agent_id, full_text, self.daemon_json, self.daemon_cache, timeout=60.0)
        send_ok = "error" not in result
        armaraos_task_id = result.get("task_id")

        node_id = store_task_episode(
            self.store, self.project_id,
            task_id, task_description, to,
            outcome="partial",
        )

        task_record = {
            "task_id": task_id,
            "armaraos_task_id": armaraos_task_id,
            "to_agent": to,
            "agent_id": agent_id,
            "task_description": task_description,
            "callback_urgency": callback_urgency,
            "status": "pending" if send_ok else "failed",
            "created_at": int(time.time()),
            "completed_at": None,
            "result": None,
            "node_id": node_id,
            "send_error": result.get("error") if not send_ok else None,
        }
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.tasks_dir / f"{task_id}.json", task_record)

        _a2a_log()(self.plugin_root, "OUT", "claude-code", to, task_id[:8], callback_urgency, task_description[:120])

        return {
            "task_id": task_id,
            "armaraos_task_id": armaraos_task_id,
            "status": task_record["status"],
            "to": to,
            "sent": send_ok,
        }

    # ── a2a_task_status ───────────────────────────────────────────────────────

    def a2a_task_status(self, task_id: str) -> Dict[str, Any]:
        task_file = self.tasks_dir / f"{task_id}.json"
        if not task_file.exists():
            return {"error": f"Task {task_id} not found"}

        task = json.loads(task_file.read_text())

        # If still pending, check ArmaraOS for the task status
        if task.get("status") == "pending":
            armaraos_task_id = task.get("armaraos_task_id")
            if armaraos_task_id:
                _, _, _, _, get_task_status_fn, _ = _a2a_client()
                remote = get_task_status_fn(
                    armaraos_task_id,
                    daemon_json_path=self.daemon_json,
                    timeout=5.0,
                )
                remote_status = remote.get("status", "")
                if remote_status == "completed" and "error" not in remote:
                    result_parts = remote.get("result", {}).get("parts", [])
                    result_text = " ".join(p.get("text", "") for p in result_parts)
                    task["status"] = "completed"
                    task["completed_at"] = int(time.time())
                    task["result"] = result_text
                    _atomic_write(task_file, task)
                elif remote_status in ("cancelled", "failed") and "error" not in remote:
                    task["status"] = remote_status
                    task["completed_at"] = int(time.time())
                    _atomic_write(task_file, task)

            # Also check local inbox as fallback (for non-ArmaraOS callbacks)
            if task.get("status") == "pending":
                inbox_dir = self.plugin_root / "a2a" / "inbox"
                for f in inbox_dir.glob("*.json"):
                    try:
                        msg = json.loads(f.read_text())
                        if msg.get("task_id") == task_id and msg.get("type") == "task_result":
                            task["status"] = "completed"
                            task["completed_at"] = int(time.time())
                            task["result"] = msg.get("message", "")
                            _atomic_write(task_file, task)
                            f.unlink(missing_ok=True)
                            break
                    except Exception:
                        continue

        return task
