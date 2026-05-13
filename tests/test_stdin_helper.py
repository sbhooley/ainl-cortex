"""Verify ``shared.stdin.read_stdin_json`` swallows the cold-start cases
that previously littered ``logs/hooks.log`` with JSONDecodeError tracebacks.

Covers Issue B2 from the post-fix audit. The helper must:
- Return ``default`` on empty stdin (cold-start with no payload).
- Return ``default`` on TTY stdin (interactive shells / tests without a pipe).
- Return ``default`` on whitespace-only stdin.
- Return ``default`` on malformed JSON, with a single warning line.
- Return the parsed dict on a valid JSON object.
- Return ``default`` (not the parsed value) on a JSON non-object (list, str).
"""
from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))

from shared.stdin import read_stdin_json  # type: ignore


class _TTYStream(io.StringIO):
    def isatty(self) -> bool:
        return True


def _patch_stdin(monkeypatch, content: str, *, tty: bool = False):
    if tty:
        stream = _TTYStream(content)
    else:
        stream = io.StringIO(content)
    monkeypatch.setattr(sys, "stdin", stream)


def test_returns_default_on_empty_stdin(monkeypatch):
    _patch_stdin(monkeypatch, "")
    assert read_stdin_json() == {}


def test_returns_default_on_whitespace_stdin(monkeypatch):
    _patch_stdin(monkeypatch, "   \n\t  ")
    assert read_stdin_json() == {}


def test_returns_default_on_tty_stdin(monkeypatch):
    _patch_stdin(monkeypatch, '{"prompt": "hi"}', tty=True)
    assert read_stdin_json() == {}


def test_parses_valid_json_object(monkeypatch):
    _patch_stdin(monkeypatch, '{"prompt": "hi", "cwd": "/tmp"}')
    parsed = read_stdin_json()
    assert parsed == {"prompt": "hi", "cwd": "/tmp"}


def test_returns_default_on_malformed_json_and_logs_warning(monkeypatch, caplog):
    _patch_stdin(monkeypatch, "not really json {[")
    with caplog.at_level(logging.WARNING):
        result = read_stdin_json(hook_name="unit_test")
    assert result == {}
    assert any("stdin was non-JSON" in rec.message for rec in caplog.records)
    assert any("[unit_test]" in rec.message for rec in caplog.records)


def test_returns_default_when_parsed_value_is_not_a_dict(monkeypatch):
    _patch_stdin(monkeypatch, '["not", "a", "dict"]')
    assert read_stdin_json() == {}


def test_default_arg_is_returned_verbatim(monkeypatch):
    _patch_stdin(monkeypatch, "")
    sentinel = {"defaulted": True}
    assert read_stdin_json(default=sentinel) is sentinel


def test_default_arg_is_fresh_dict_per_call_when_unset(monkeypatch):
    _patch_stdin(monkeypatch, "")
    a = read_stdin_json()
    _patch_stdin(monkeypatch, "")
    b = read_stdin_json()
    a["mutated"] = True  # must not bleed into b
    assert "mutated" not in b
