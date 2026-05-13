"""
Cached config reader for hooks.

Hooks run as fresh subprocesses per Claude Code event, so the cache scope is one
hook invocation. The 30s TTL is paranoia for any long-lived process that might
import this module (e.g. the MCP server reusing it via PYTHONPATH).

Centralising the lookup also gives a single place to add an env-var override
(`AINL_CORTEX_STORE_BACKEND`) when we need to force a backend for testing
without editing config.json.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Cache: (loaded_at_unix_seconds, parsed_config_dict)
_CACHE: tuple[float, Dict[str, Any]] | None = None
_CACHE_TTL_S = 30.0

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_PATH = _PLUGIN_ROOT / "config.json"


def _load_raw() -> Dict[str, Any]:
    """Read and parse config.json. Returns {} on any error so callers can
    use `.get()` chains without try/except."""
    try:
        return json.loads(_CONFIG_PATH.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def read_config(force_refresh: bool = False) -> Dict[str, Any]:
    """Return the parsed plugin config. Cached for `_CACHE_TTL_S` seconds.

    `force_refresh=True` bypasses the cache (used by tests and by hot-reload
    paths in the MCP server)."""
    global _CACHE
    now = time.time()
    if not force_refresh and _CACHE is not None:
        loaded_at, cached = _CACHE
        if now - loaded_at < _CACHE_TTL_S:
            return cached
    cfg = _load_raw()
    _CACHE = (now, cfg)
    return cfg


def get_backend() -> str:
    """Return the active store backend: 'native' or 'python'.

    Order of precedence: env override > config.json > default 'python'.
    """
    env_override = os.environ.get("AINL_CORTEX_STORE_BACKEND", "").strip().lower()
    if env_override in ("native", "python"):
        return env_override
    cfg = read_config()
    raw = (cfg.get("memory", {}) or {}).get("store_backend", "python")
    return "native" if str(raw).lower() == "native" else "python"


def is_strict_native(native_loaded: bool) -> bool:
    """True iff the plugin should run in strict-native mode for THIS process.

    Strict-native means: the Rust pipeline is the source of truth for episodes,
    semantics, procedurals, persona, and the anchored summary. Python writes
    those node types are skipped to avoid the dual-write divergence documented
    in CLAUDE.md (see "Database files").

    Two carve-outs (Python sidecar) remain even in strict-native mode:
      - write_failures: the Rust pipeline derives failures from trajectory
        steps only. Python's _BASH_FAILURE_RE post-hoc scan catches errors
        whose tool call was never recorded as a trajectory step.
      - write_goals: the Rust crates do not have a goal tracker yet.

    `native_loaded` is the caller's `_NATIVE_OK` import flag — strict-native
    requires both config selection AND a successful PyO3 module import.
    """
    return native_loaded and get_backend() == "native"


def reset_cache() -> None:
    """Clear the in-process config cache. Used by tests."""
    global _CACHE
    _CACHE = None
