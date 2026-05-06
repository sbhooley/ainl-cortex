"""
A2A human-readable log writer.

Appends one line per message to a2a/logs/a2a.log.
Format: ISO timestamp  DIR  from/to  thread  urgency  "preview..."
"""

import fcntl
import time
from pathlib import Path


def append_log(
    plugin_root: Path,
    direction: str,          # "IN" or "OUT"
    from_agent: str,
    to_agent: str,
    thread_id: str,
    urgency: str,
    message_preview: str,
    status: str = "ok",
) -> None:
    log_path = plugin_root / "a2a" / "logs" / "a2a.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tid = (thread_id or "none")[:12]
    preview = (message_preview or "").replace("\n", " ")[:120]
    if len(message_preview or "") > 120:
        preview += "..."

    line = (
        f"{ts}  {direction:<3}  "
        f"from:{from_agent:<20}  to:{to_agent:<20}  "
        f"thread:{tid:<12}  urgency:{urgency:<8}  "
        f"status:{status}  \"{preview}\"\n"
    )

    try:
        with open(log_path, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(line)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except Exception:
        pass  # log write failure is always non-fatal
