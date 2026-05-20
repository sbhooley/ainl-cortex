"""Shared pytest path setup — package-mode imports for mcp_server + hooks."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
HOOKS_ROOT = PLUGIN_ROOT / "hooks"

# Flat hook modules and package aliases that must not stick to a stale tmp checkout.
_HOOK_MODULE_NAMES = frozenset({
    "startup",
    "stop",
    "user_prompt_submit",
    "post_tool_use",
    "pre_compact",
    "config",
    "graph_store",
    "native_graph_store",
    "failure_advisor",
    "server",
    "hooks",
    "hooks.startup",
    "hooks.stop",
    "hooks.shared",
    "hooks.shared.conversation_detection",
})


def _stale_plugin_path(entry: str) -> bool:
    if "ainl-cortex-fresh" in entry:
        return True
    resolved = str(PLUGIN_ROOT)
    if entry == resolved or entry.startswith(resolved + "/"):
        return False
    if ("ainl-cortex" in entry or "ainl_cortex" in entry) and (
        "/private/tmp/" in entry or entry.startswith("/tmp/")
    ):
        return True
    return False


def _apply_plugin_path_hygiene() -> None:
    """Keep PLUGIN_ROOT ahead of stale PYTHONPATH / tmp checkouts."""
    sys.path[:] = [p for p in sys.path if not _stale_plugin_path(p)]
    raw = os.environ.get("PYTHONPATH", "")
    if raw:
        parts = [p for p in raw.split(os.pathsep) if p and not _stale_plugin_path(p)]
        if parts:
            os.environ["PYTHONPATH"] = os.pathsep.join(parts)
        else:
            os.environ.pop("PYTHONPATH", None)
    for entry in (str(PLUGIN_ROOT), str(HOOKS_ROOT)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    mcp_str = str(PLUGIN_ROOT / "mcp_server")
    sys.path[:] = [p for p in sys.path if p != mcp_str]


def _purge_stale_hook_modules() -> None:
    for name in list(sys.modules):
        mod = sys.modules.get(name)
        if mod is None:
            del sys.modules[name]
            continue
        mod_file = getattr(mod, "__file__", None) or ""
        if mod_file and _stale_plugin_path(mod_file):
            del sys.modules[name]
            continue
        if name in _HOOK_MODULE_NAMES or name.startswith("hooks."):
            continue
        # Drop cached hook modules so the next test reloads from PLUGIN_ROOT.
        if name in ("stop", "startup", "user_prompt_submit", "post_tool_use", "pre_compact"):
            del sys.modules[name]


def _purge_native_binding_cache() -> None:
    """Remove mocked ainl_native left by strict-native tests (breaks skipif)."""
    for name in ("ainl_native", "native_graph_store", "mcp_server.native_graph_store"):
        if name in sys.modules:
            del sys.modules[name]


_INBOX_TEST_PROJECTS = (
    "proj_decision_test",
    "proj_dedup_test",
    "proj_toofew",
    "proj_branch_jsonl_test",
    "proj_branch_git_test",
)


@pytest.fixture(autouse=True)
def _plugin_import_hygiene():
    """Reset sys.path / cached hook modules polluted by PYTHONPATH or prior tests."""
    _apply_plugin_path_hygiene()
    _purge_stale_hook_modules()
    _purge_native_binding_cache()
    yield
    _apply_plugin_path_hygiene()
    _purge_stale_hook_modules()
    _purge_native_binding_cache()


@pytest.fixture(autouse=True)
def _isolate_prompt_history_inbox():
    """Prevent cross-test pollution of PLUGIN_ROOT/inbox/*_prompts.jsonl fixtures."""
    inbox = PLUGIN_ROOT / "inbox"
    for pid in _INBOX_TEST_PROJECTS:
        hist = inbox / f"{pid}_prompts.jsonl"
        if hist.exists():
            hist.unlink()
    yield
    for pid in _INBOX_TEST_PROJECTS:
        hist = inbox / f"{pid}_prompts.jsonl"
        if hist.exists():
            hist.unlink()


def pytest_configure(config):
    _apply_plugin_path_hygiene()
    _purge_stale_hook_modules()
