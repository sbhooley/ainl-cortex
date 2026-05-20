"""SessionStart transcript + terminal notification helpers."""

import json
from pathlib import Path

from hooks.shared.sessionstart_visibility import (
    build_sessionstart_terminal_sequence,
    consume_transcript_pending,
    first_banner_line,
    write_transcript_pending,
)


def test_first_banner_line():
    msg = "line1\n[AINL Cortex]  ~/\n  • ok"
    assert first_banner_line(msg) == "line1"


def test_transcript_pending_roundtrip(tmp_path):
    root = tmp_path / "plugin"
    root.mkdir()
    write_transcript_pending(root, "sess-1", "[AINL Cortex] ready")
    assert consume_transcript_pending(root, "sess-1") == "[AINL Cortex] ready"
    assert consume_transcript_pending(root, "sess-1") is None


def test_terminal_sequence_allowlisted():
    seq = build_sessionstart_terminal_sequence("[AINL Cortex] ok")
    assert "\033]9;" in seq
    assert "\033]777;notify;" in seq


def test_terminal_sequence_disabled(monkeypatch):
    monkeypatch.setenv("AINL_CORTEX_SESSIONSTART_NOTIFY", "0")
    assert build_sessionstart_terminal_sequence("x") == ""
