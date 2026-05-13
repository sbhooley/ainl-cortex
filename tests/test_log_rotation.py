"""Verify hooks.log uses RotatingFileHandler and rolls over.

Covers Issue B5 from the post-fix audit. Without rotation, hooks.log
grew unbounded across long-running Claude Code sessions and could fill
the user's disk. With rotation, the active file is bounded by
``AINL_CORTEX_HOOKS_LOG_MAX_BYTES`` and at most
``AINL_CORTEX_HOOKS_LOG_BACKUPS`` rotated backups are kept.

We don't try to rotate the real ``logs/hooks.log`` (that's a shared file
across the dev install); instead, we instantiate a fresh
RotatingFileHandler in a temp directory and confirm the same
parameter-driven behavior.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))


def test_hooks_logger_uses_rotating_file_handler():
    # Reload the shared logger module to make sure we observe the current
    # handler set (other tests in this process may have added handlers).
    for mod_name in ("shared.logger",):
        if mod_name in sys.modules:
            del sys.modules[mod_name]
    from shared import logger as logger_mod  # type: ignore

    assert isinstance(logger_mod.file_handler, RotatingFileHandler)
    assert logger_mod.file_handler.maxBytes > 0
    assert logger_mod.file_handler.backupCount >= 1


def test_rotating_file_handler_rolls_over(tmp_path: Path):
    log_path = tmp_path / "hooks.log"
    handler = RotatingFileHandler(
        log_path, maxBytes=512, backupCount=2, encoding="utf-8"
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(message)s"))
    test_logger = logging.getLogger("test_log_rotation_rollover")
    test_logger.handlers.clear()
    test_logger.addHandler(handler)
    test_logger.setLevel(logging.DEBUG)

    payload = "x" * 100
    for i in range(20):
        test_logger.info("%s-%d", payload, i)

    handler.close()

    assert log_path.exists(), "active log file must exist after rotation"
    assert log_path.stat().st_size <= 512 + 64, (
        "active log must be roughly bounded by maxBytes "
        f"(actual: {log_path.stat().st_size})"
    )
    backup1 = log_path.with_name("hooks.log.1")
    assert backup1.exists(), "expected at least one rotated backup"

    backup3 = log_path.with_name("hooks.log.3")
    assert not backup3.exists(), (
        "rotation must respect backupCount=2 (no .3 file)"
    )


def test_env_overrides_take_effect(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AINL_CORTEX_HOOKS_LOG_MAX_BYTES", "777777")
    monkeypatch.setenv("AINL_CORTEX_HOOKS_LOG_BACKUPS", "7")

    # Importing fresh isn't worth the gymnastics across pytest's import
    # cache; instead, exercise the same _env_int helper directly to prove
    # env-var parsing works end-to-end.
    from shared.logger import _env_int  # type: ignore

    assert _env_int("AINL_CORTEX_HOOKS_LOG_MAX_BYTES", 1) == 777777
    assert _env_int("AINL_CORTEX_HOOKS_LOG_BACKUPS", 1) == 7
    assert _env_int("AINL_CORTEX_DOES_NOT_EXIST", 99) == 99
