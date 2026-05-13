"""Shared stdin parsing helpers for Claude Code hook entrypoints.

Centralizes the resilient `json.load(sys.stdin)` pattern that several hooks
reimplemented inline. Some hooks were calling `json.load(sys.stdin)`
unguarded, which raises ``json.JSONDecodeError: Expecting value: line 1
column 1 (char 0)`` when Claude Code spawns the hook with empty stdin
(e.g. cold-start with no event payload yet) — those tracebacks then end
up in `logs/hooks.log` and look like real failures.

Behavior:
- Empty/whitespace stdin → returns ``default`` (typically ``{}``).
- TTY stdin (no piped input) → returns ``default``.
- Malformed JSON → returns ``default`` and writes a single-line warning to
  the optional ``logger`` rather than tracebacking.

Use :func:`read_stdin_json` everywhere a hook would otherwise call
``json.load(sys.stdin)``.
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any, Mapping, Optional


_DEFAULT_LOGGER = logging.getLogger(__name__)


def read_stdin_json(
    default: Optional[Mapping[str, Any]] = None,
    *,
    logger: Optional[logging.Logger] = None,
    hook_name: Optional[str] = None,
) -> Mapping[str, Any]:
    """Read and parse a JSON object from stdin, returning ``default`` on
    any failure.

    Args:
        default: Value to return when stdin is empty/TTY/malformed. Defaults
            to ``{}`` (a fresh empty dict per call so callers can mutate
            without aliasing).
        logger: Logger for the single-line warning emitted on a real
            JSONDecodeError (empty/TTY paths stay silent — they are normal).
        hook_name: Optional caller name to include in the warning, useful
            when several hooks share the same logfile.
    """
    if default is None:
        default = {}

    log = logger or _DEFAULT_LOGGER

    try:
        if sys.stdin is None or sys.stdin.isatty():
            return default
    except (OSError, AttributeError):
        return default

    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return default

    if not raw or not raw.strip():
        return default

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        prefix = f"[{hook_name}] " if hook_name else ""
        log.warning(
            "%sstdin was non-JSON (%d bytes); returning default. error=%s",
            prefix,
            len(raw),
            exc.msg,
        )
        return default

    if not isinstance(parsed, dict):
        return default

    return parsed
