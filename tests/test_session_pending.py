"""Session pending accumulator (per-prompt flush vs stop finalize)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

from shared.session_pending import (
    accumulate_into_pending,
    clear_pending_session,
    collect_session_for_finalize,
    empty_session,
    merge_session_batches,
)


@pytest.fixture
def inbox(tmp_path):
    d = tmp_path / "inbox"
    d.mkdir()
    return d


def test_merge_session_batches_unions_captures_and_flags():
    a = {
        "tool_captures": [{"tool": "a", "success": True}],
        "files_touched": ["/x.py"],
        "tools_used": ["Read"],
        "had_errors": False,
        "turn_id": "turn-a",
    }
    b = {
        "tool_captures": [{"tool": "b", "success": False}],
        "files_touched": ["/y.py"],
        "tools_used": ["Bash"],
        "had_errors": True,
    }
    m = merge_session_batches(a, b)
    assert len(m["tool_captures"]) == 2
    assert set(m["files_touched"]) == {"/x.py", "/y.py"}
    assert m["had_errors"] is True
    assert m["turn_id"] == "turn-a"


def test_accumulate_and_collect_clears_pending(inbox):
    batch1 = {
        "tool_captures": [{"tool": "bash", "success": True}],
        "files_touched": ["/a.py"],
        "tools_used": ["bash"],
        "had_errors": False,
    }
    accumulate_into_pending(inbox, "proj", batch1)
    path = inbox / "proj_session_pending.json"
    assert path.exists()

    batch2 = {
        "tool_captures": [{"tool": "bash", "success": False, "error": "fail"}],
        "files_touched": ["/b.py"],
        "tools_used": ["bash"],
        "had_errors": True,
    }
    merged = collect_session_for_finalize(inbox, "proj", batch2)
    assert len(merged["tool_captures"]) == 2
    assert merged["had_errors"] is True
    assert not path.exists()


def test_collect_with_empty_batch_returns_pending_only(inbox):
    pending = {
        "tool_captures": [{"tool": "x", "success": True}],
        "files_touched": [],
        "tools_used": ["x"],
        "had_errors": False,
    }
    (inbox / "proj_session_pending.json").write_text(json.dumps(pending))
    out = collect_session_for_finalize(inbox, "proj", empty_session())
    assert len(out["tool_captures"]) == 1
    clear_pending_session(inbox, "proj")
