#!/usr/bin/env python3
"""
A2A inbox writer — delegate script for HERMES_AINL_BRIDGE_CMD.

The A2A bridge calls this script with the inbound message text on stdin.
We write a structured JSON file to the plugin inbox and print "ok" to
stdout so the bridge marks the task completed.

Zero plugin imports — stdlib only so any Python 3.8+ installation works.
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path


PLUGIN_ROOT = Path(os.environ.get("AINL_PLUGIN_ROOT", Path(__file__).resolve().parent.parent))
INBOX_DIR = PLUGIN_ROOT / "a2a" / "inbox"


def extract_header(text: str, header: str, default: str = "") -> str:
    """Extract X-Header: value from message text (convention for structured sends)."""
    prefix = f"{header}: "
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return default


def strip_headers(text: str) -> str:
    """Remove X-* header lines from message body."""
    lines = []
    for line in text.splitlines():
        if not (line.startswith("X-") and ": " in line):
            lines.append(line)
    return "\n".join(lines).strip()


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        print("ok")
        return

    msg_id = str(uuid.uuid4())
    from_agent = extract_header(raw, "X-From-Agent", "unknown")
    urgency = extract_header(raw, "X-Urgency", "normal")
    thread_id = extract_header(raw, "X-Thread-Id") or None
    task_id = extract_header(raw, "X-Task-Id") or None
    msg_type = "task_result" if task_id else "message"
    body = strip_headers(raw)

    msg = {
        "id": msg_id,
        "type": msg_type,
        "from_agent": from_agent,
        "to_agent": "claude-code",
        "thread_id": thread_id,
        "task_id": task_id,
        "message": body,
        "urgency": urgency if urgency in ("critical", "normal", "low") else "normal",
        "received_at": int(time.time()),
    }

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    tmp = INBOX_DIR / f"{msg_id}.tmp"
    dest = INBOX_DIR / f"{msg_id}.json"
    tmp.write_text(json.dumps(msg, indent=2))
    os.replace(tmp, dest)

    print("ok")


if __name__ == "__main__":
    main()
