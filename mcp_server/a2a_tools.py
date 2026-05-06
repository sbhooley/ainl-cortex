"""
A2A MCP tool implementations.

Provides 7 tools: a2a_send, a2a_list_agents, a2a_register_agent,
a2a_note_to_self, a2a_register_monitor, a2a_task_send, a2a_task_status.
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

# Lazy import of hook-side stdlib utilities (no venv needed)
def _a2a_log():
    from shared.a2a_log import append_log
    return append_log

def _a2a_inbox():
    from shared.a2a_inbox import write_self_note
    return write_self_note

def _a2a_client():
    from shared.a2a_client import post_a2a, get_agent_card, is_bridge_alive
    return post_a2a, get_agent_card, is_bridge_alive


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
        self.host = self.cfg.get("bridge_host", "127.0.0.1")
        self.port = int(self.cfg.get("bridge_port", 7860))
        self.bridge_url = f"http://{self.host}:{self.port}"
        self.registry_path = plugin_root / "a2a" / "agents" / "registry.json"
        self.tasks_dir = plugin_root / "a2a" / "tasks"
        self.monitors_path = plugin_root / "a2a" / "monitors" / "monitor_configs.json"

    def _registry(self) -> dict:
        return _read_json(self.registry_path, {})

    def _save_registry(self, reg: dict) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.registry_path, reg)

    def _bridge_alive(self) -> bool:
        _, _, is_alive = _a2a_client()
        return is_alive(self.host, self.port)

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
            return {"error": f"Agent '{to}' not registered. Use a2a_register_agent first.", "registered_agents": list(reg.keys())}

        agent = reg[to]
        agent_url = agent["url"]
        tid = thread_id or str(uuid.uuid4())

        # Prepend structured headers so the remote inbox_writer can parse them
        full_message = (
            f"X-From-Agent: claude-code\n"
            f"X-Thread-Id: {tid}\n"
            f"X-Urgency: {urgency}\n"
            f"{message}"
        )

        post_a2a, _, _ = _a2a_client()
        result = post_a2a(
            agent_url,
            "tasks/send",
            {"message": {"parts": [{"type": "text", "text": full_message}]}},
            timeout=5.0,
        )

        if result.get("error"):
            _a2a_log()(self.plugin_root, "OUT", "claude-code", to, tid, urgency, message[:120], status="fail")
            return {"sent": False, "error": result["error"], "thread_id": tid}

        store_message_node(self.store, self.project_id, "outbound", "claude-code", to, tid, urgency, message)
        _a2a_log()(self.plugin_root, "OUT", "claude-code", to, tid, urgency, message[:120])

        # Update last_seen_at
        reg[to]["last_seen_at"] = int(time.time())
        self._save_registry(reg)

        return {"sent": True, "to": to, "thread_id": tid, "urgency": urgency}

    # ── a2a_list_agents ───────────────────────────────────────────────────────

    def a2a_list_agents(self) -> Dict[str, Any]:
        reg = self._registry()
        _, get_agent_card, is_alive = _a2a_client()
        agents = []
        for name, info in reg.items():
            entry = dict(info)
            try:
                card = get_agent_card(info["url"], timeout=2.0)
                entry["reachable"] = "error" not in card
                entry["capabilities"] = card.get("capabilities", info.get("capabilities", []))
            except Exception:
                entry["reachable"] = False
            agents.append(entry)

        return {
            "agents": agents,
            "count": len(agents),
            "bridge_running": self._bridge_alive(),
        }

    # ── a2a_register_agent ────────────────────────────────────────────────────

    def a2a_register_agent(
        self,
        name: str,
        url: str,
        description: str,
        capabilities: Optional[list] = None,
    ) -> Dict[str, Any]:
        if not url.startswith(("http://", "https://")):
            return {"error": "url must start with http:// or https://"}

        reg = self._registry()
        reg[name] = {
            "name": name,
            "url": url,
            "description": description,
            "capabilities": capabilities or [],
            "registered_at": int(time.time()),
            "last_seen_at": None,
        }
        self._save_registry(reg)
        return {"registered": True, "name": name, "url": url}

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
        agent_url = reg[to]["url"]

        full_message = (
            f"X-From-Agent: claude-code\n"
            f"X-Task-Id: {task_id}\n"
            f"X-Urgency: {callback_urgency}\n"
            f"{task_description}"
        )

        post_a2a, _, _ = _a2a_client()
        result = post_a2a(
            agent_url,
            "tasks/send",
            {"message": {"parts": [{"type": "text", "text": full_message}]}},
            timeout=5.0,
        )

        send_ok = "error" not in result
        outcome = "partial" if not send_ok else "partial"  # pending until callback

        node_id = store_task_episode(
            self.store, self.project_id,
            task_id, task_description, to,
            outcome="partial",
        )

        task_record = {
            "task_id": task_id,
            "to_agent": to,
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

        # Check inbox for a completion callback if still pending
        if task.get("status") == "pending":
            from pathlib import Path as _Path
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
