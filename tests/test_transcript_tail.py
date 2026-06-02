"""Transcript tail parsing for remember ingest."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _path():
    p = str(PLUGIN_ROOT / "mcp_server")
    if p not in sys.path:
        sys.path.insert(0, p)


def test_strip_remember_prefix():
    from transcript_tail import strip_remember_command_prefix

    body = strip_remember_command_prefix(
        "remember this\n\nCraigcast uses 9:16 vertical clips with captions."
    )
    assert "Craigcast" in body
    assert "remember this" not in body.lower()


def test_read_last_assistant_text(tmp_path):
    from transcript_tail import read_last_assistant_text

    path = tmp_path / "sess.jsonl"
    records = [
        {"type": "user", "message": {"role": "user", "content": "hi"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Short."},
                ],
            },
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "Research summary: viral hooks need pattern interrupts in the first 2 seconds.",
                    },
                ],
            },
        },
    ]
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    text = read_last_assistant_text(path, min_chars=40)
    assert "pattern interrupts" in text
