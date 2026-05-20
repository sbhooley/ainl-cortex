"""Autonomous scheduled-task MCP handlers (SQLite autonomous_tasks + scope lock)."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .autonomous_scheduler import is_valid_schedule, parse_next_run
    from .graph_store import append_execution_log
except ImportError:
    from autonomous_scheduler import is_valid_schedule, parse_next_run
    from graph_store import append_execution_log

_VALID_RISK_TIERS = frozenset({"read_only", "memory_ops", "file_write", "external_send"})

_ALWAYS_ALLOWED_IN_TASK = frozenset({
    "memory_complete_task",
    "memory_cancel_task",
    "memory_begin_task_execution",
    "memory_approve_task",
    "memory_list_scheduled_tasks",
    "memory_list_autonomous_executions",
})


def _plugin_root() -> Path:
    import os

    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent


def _active_task_path() -> Path:
    return _plugin_root() / "logs" / "active_task.json"


def _parse_json_field(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def _path_matches_scope(cwd: str, scope_paths: List[str]) -> bool:
    for base in scope_paths:
        base = str(base).rstrip("/")
        if cwd == base or cwd.startswith(base + "/"):
            return True
    return False


def check_task_scope_lock(tool_name: str) -> Optional[Dict[str, Any]]:
    """Return block payload if tool is not allowed under active_task.json."""
    try:
        sidecar = _active_task_path()
        if not sidecar.is_file():
            return None
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        allowed = data.get("allowed_actions")
        if not allowed:
            return None
        if isinstance(allowed, str):
            allowed = json.loads(allowed)
        if tool_name in _ALWAYS_ALLOWED_IN_TASK:
            return None
        if tool_name not in allowed:
            return {
                "error": "tool_blocked_by_task_scope",
                "tool_called": tool_name,
                "allowed_actions": allowed,
                "task_id": data.get("task_id"),
                "hint": "Call memory_complete_task or use a whitelisted tool.",
            }
    except Exception:
        pass
    return None


def _clear_scope_lock(task_id: Optional[str] = None) -> bool:
    """Remove active_task.json; only clear if task_id matches when provided."""
    try:
        sidecar = _active_task_path()
        if not sidecar.is_file():
            return False
        if task_id:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            if data.get("task_id") != task_id:
                return False
        sidecar.unlink()
        return True
    except Exception:
        return False


def _read_session_id(project_id: str) -> Optional[str]:
    try:
        path = _plugin_root() / "inbox" / f"{project_id}_session_id.txt"
        if path.is_file():
            return path.read_text(encoding="utf-8").strip() or None
    except Exception:
        pass
    return None


async def memory_schedule_task(
    store: Any,
    project_id: str,
    description: str,
    schedule: Optional[str] = None,
    priority: int = 5,
    max_runs: Optional[int] = None,
    created_by: str = "user",
    risk_tier: str = "read_only",
    allowed_actions: Optional[List[str]] = None,
    path_scope: Optional[List[str]] = None,
    run_now: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    if risk_tier not in _VALID_RISK_TIERS:
        return {"error": f"invalid risk_tier: {risk_tier}"}
    if schedule and not is_valid_schedule(schedule):
        return {"error": f"invalid schedule: {schedule}"}
    if not (1 <= int(priority) <= 10):
        return {"error": "priority must be between 1 and 10"}

    next_run_at: Optional[float] = None
    if run_now:
        next_run_at = time.time()
    elif schedule:
        next_run_at = parse_next_run(schedule)

    task_id = str(uuid.uuid4())
    task = store.create_autonomous_task(
        task_id=task_id,
        project_id=project_id,
        description=description,
        schedule=schedule,
        next_run_at=next_run_at,
        created_by=created_by,
        max_runs=max_runs,
        priority=int(priority),
        allowed_actions=allowed_actions,
        risk_tier=risk_tier,
        path_scope=path_scope,
    )
    requires_approval = risk_tier != "read_only"
    return {
        "task_id": task_id,
        "task": task,
        "requires_approval": requires_approval,
        "approved_by": task.get("approved_by"),
    }


async def memory_approve_task(store: Any, task_id: str, **kwargs: Any) -> Dict[str, Any]:
    task = store.get_autonomous_task(task_id)
    if not task:
        return {"error": "task_not_found", "task_id": task_id}
    if task.get("risk_tier") == "read_only" or task.get("approved_by") == "system":
        return {
            "ok": True,
            "task_id": task_id,
            "approved_by": "system",
            "note": "read_only tasks are auto-approved",
        }
    store.update_autonomous_task(task_id, approved_by="user")
    return {"ok": True, "task_id": task_id, "approved_by": "user"}


async def memory_begin_task_execution(
    store: Any,
    task_id: str,
    project_id: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    task = store.get_autonomous_task(task_id)
    if not task:
        return {"error": "task_not_found", "task_id": task_id}

    allowed = _parse_json_field(task.get("allowed_actions"))
    record = {
        "task_id": task_id,
        "project_id": project_id,
        "allowed_actions": allowed,
        "risk_tier": task.get("risk_tier", "read_only"),
        "started_at": time.time(),
    }
    sidecar = _active_task_path()
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(record), encoding="utf-8")
    scope_lock_active = bool(allowed)
    return {"ok": True, "task_id": task_id, "scope_lock_active": scope_lock_active}


async def memory_complete_task(
    store: Any,
    task_id: str,
    note: Optional[str] = None,
    reschedule: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    task = store.get_autonomous_task(task_id)
    if not task:
        return {"error": "task_not_found", "task_id": task_id}

    next_run_at: Optional[float] = None
    rescheduled = False
    schedule = task.get("schedule")
    if reschedule and schedule:
        try:
            next_run_at = parse_next_run(schedule)
            rescheduled = True
        except (ValueError, TypeError):  # bad schedule must not crash scope lock
            next_run_at = None

    store.mark_task_run(task_id, run_status="success", note=note, next_run_at=next_run_at)
    updated = store.get_autonomous_task(task_id) or task

    project_id = updated.get("project_id") or task.get("project_id") or ""
    session_id = _read_session_id(project_id)
    append_execution_log(
        _plugin_root(),
        updated,
        "success",
        note,
        cwd=str(Path.cwd()),
        session_id=session_id,
    )
    scope_lock_cleared = _clear_scope_lock(task_id)
    completed = updated.get("status") == "completed"
    return {
        "completed": completed,
        "task_id": task_id,
        "rescheduled": rescheduled,
        "scope_lock_cleared": scope_lock_cleared,
        "execution_logged": True,
    }


async def memory_cancel_task(store: Any, task_id: str, **kwargs: Any) -> Dict[str, Any]:
    task = store.get_autonomous_task(task_id)
    if not task:
        return {"error": "task_not_found", "task_id": task_id}
    store.cancel_autonomous_task(task_id)
    scope_lock_cleared = _clear_scope_lock(task_id)
    return {"cancelled": True, "task_id": task_id, "scope_lock_cleared": scope_lock_cleared}


async def memory_update_task(store: Any, task_id: str, **kwargs: Any) -> Dict[str, Any]:
    if "priority" in kwargs:
        pri = kwargs["priority"]
        if pri is not None and not (1 <= int(pri) <= 10):
            return {"error": "priority must be between 1 and 10"}

    task = store.get_autonomous_task(task_id)
    if not task:
        return {"error": "task_not_found", "task_id": task_id}

    updates: Dict[str, Any] = {}
    for key in (
        "description",
        "schedule",
        "priority",
        "status",
        "max_runs",
        "risk_tier",
        "approved_by",
    ):
        if key in kwargs and kwargs[key] is not None:
            updates[key] = kwargs[key]

    if "allowed_actions" in kwargs and kwargs["allowed_actions"] is not None:
        aa = kwargs["allowed_actions"]
        updates["allowed_actions"] = json.dumps(aa) if isinstance(aa, list) else aa

    if "path_scope" in kwargs and kwargs["path_scope"] is not None:
        ps = kwargs["path_scope"]
        updates["path_scope"] = json.dumps(ps) if isinstance(ps, list) else ps

    if "schedule" in updates and updates["schedule"]:
        if not is_valid_schedule(str(updates["schedule"])):
            return {"error": f"invalid schedule: {updates['schedule']}"}
        updates["next_run_at"] = parse_next_run(str(updates["schedule"]))

    if not updates:
        return {"error": "no valid fields to update"}

    ok = store.update_autonomous_task(task_id, **updates)
    if not ok:
        return {"error": "update_failed", "task_id": task_id}
    return {"ok": True, "task_id": task_id, "updated": list(updates.keys())}


async def memory_list_scheduled_tasks(
    store: Any,
    project_id: str,
    status: str = "active",
    due_only: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    tasks = store.list_autonomous_tasks(project_id, status=status, due_only=due_only)
    now = time.time()
    enriched = []
    for t in tasks:
        row = dict(t)
        nra = row.get("next_run_at")
        if nra is not None:
            row["seconds_until_due"] = max(0, int(nra - now))
        enriched.append(row)
    return {"count": len(enriched), "tasks": enriched}


async def memory_list_autonomous_executions(
    project_id: Optional[str] = None,
    limit: int = 50,
    **kwargs: Any,
) -> Dict[str, Any]:
    log_file = _plugin_root() / "logs" / "autonomous_executions.jsonl"
    if not log_file.is_file():
        return {"total": 0, "executions": []}
    rows: List[Dict[str, Any]] = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if project_id and rec.get("project_id") != project_id:
            continue
        rows.append(rec)
    rows = rows[-limit:]
    return {"total": len(rows), "executions": rows}
