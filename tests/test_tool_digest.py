"""Zero-LLM tool result digests."""

from mcp_server.tool_digest import build_digest, load_tool_outcome_blob, should_digest, store_tool_outcome_blob


def test_should_digest_large_read():
    text = "x" * 5000
    assert should_digest("read", text)


def test_build_digest_caps_size():
    text = "error: failed\n" + ("line\n" * 200)
    d = build_digest("grep", text, max_chars=500)
    assert len(d) <= 520
    assert "grep" in d


def test_store_and_load_blob(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    pid = "testproj"
    blob_id = "abc123"
    store_tool_outcome_blob(tmp_path, pid, blob_id, "full payload here")
    loaded = load_tool_outcome_blob(pid, blob_id)
    assert loaded == "full payload here"
