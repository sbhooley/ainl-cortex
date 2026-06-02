"""Cross-platform battle tests for knowledge capture + remember ingest."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _path():
    for p in (
        str(PLUGIN_ROOT / "tests"),
        str(PLUGIN_ROOT / "mcp_server"),
        str(PLUGIN_ROOT / "hooks"),
    ):
        if p not in sys.path:
            sys.path.insert(0, p)


def _bind_store(monkeypatch, project_id: str, db: Path):
    from knowledge_test_util import bind_test_graph_store

    return bind_test_graph_store(monkeypatch, project_id, db)


def test_encode_claude_cwd_slug_unix():
    from claude_paths import encode_claude_cwd_slug

    assert encode_claude_cwd_slug(Path("/Users/alice")) == "-Users-alice"


def test_encode_claude_cwd_slug_windows():
    from claude_paths import encode_claude_cwd_slug

    slug = encode_claude_cwd_slug(Path("C:/Users/alice"))
    assert slug == "-C-Users-alice"
    slug2 = encode_claude_cwd_slug(Path(r"C:\Users\alice"))
    assert slug2 == "-C-Users-alice"


def test_memory_bridge_resolves_windows_encoded_dir(tmp_path, monkeypatch):
    from claude_memory_bridge import _resolve_memory_dir

    home = tmp_path / "home"
    mem = home / ".claude" / "projects" / "-C-Users-dev" / "memory"
    mem.mkdir(parents=True)
    (mem / "reference_test.md").write_text(
        "- Craigcast clips use 9:16 vertical format with burned captions.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("claude_paths.Path.home", lambda: home)

    found = _resolve_memory_dir("proj1", cwd=Path(r"C:\Users\dev"))
    assert found == mem


def test_artifact_ingest_windows_path_key(tmp_path):
    from artifact_ingest import collect_ingest_paths

    win_file = tmp_path / "plan.md"
    win_file.write_text("# Plan\n" + ("x" * 300), encoding="utf-8")
    raw = str(win_file).replace("/", "\\") if "\\" in str(tmp_path) else str(win_file)

    session = {
        "tool_captures": [
            {"ingest_candidate": True, "file": raw},
            {"ingest_candidate": True, "file": raw},
        ]
    }
    paths = collect_ingest_paths(session)
    assert len(paths) == 1


def test_transcript_crlf_and_windows_path(tmp_path):
    from transcript_tail import read_last_assistant_text

    path = tmp_path / "sess.jsonl"
    rec = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Algorithm note: LinkedIn favors native video uploads over "
                        "external links in the first hour after posting."
                    ),
                }
            ],
        },
    }
    path.write_bytes((json.dumps(rec) + "\r\n").encode("utf-8"))
    win_path = str(path).replace("/", "\\") if "\\" in str(path) else str(path)
    text = read_last_assistant_text(win_path, min_chars=40)
    assert "LinkedIn" in text


def test_knowledge_pipeline_smoke(tmp_path, monkeypatch):
    from artifact_ingest import read_artifact_text
    from knowledge_pipeline import run_knowledge_capture

    project_id = "xplat_pipeline_test"
    db = tmp_path / "ainl_memory.db"
    _bind_store(monkeypatch, project_id, db)

    art = tmp_path / "game_plan.md"
    art.write_text(
        "## Hooks\n\n- Use pattern interrupt in first 2 seconds.\n\n"
        + ("Detail line with metrics 40% retention.\n" * 15),
        encoding="utf-8",
    )

    session = {
        "tool_captures": [
            {
                "tool": "write",
                "ingest_candidate": True,
                "file": str(art),
                "success": True,
            },
            {
                "tool": "web_search",
                "tool_digest": "web_search: tiktok algorithm favors watch time",
                "success": True,
            },
        ],
        "files_touched": [str(art)],
        "tools_used": ["write", "web_search"],
        "had_errors": False,
    }

    assert read_artifact_text(art, 512_000)
    out = run_knowledge_capture(
        project_id,
        session,
        "Researched clipping and social algorithms",
        plugin_root=PLUGIN_ROOT,
        cwd=tmp_path,
    )
    assert out.get("artifact", {}).get("written", 0) >= 1


def test_prompt_remember_with_crlf_transcript(plugin_inbox, monkeypatch, tmp_path):
    from prompt_remember_ingest import run

    project_id = "xplat_remember"
    db = tmp_path / "db.sqlite"
    _bind_store(monkeypatch, project_id, db)

    transcript = tmp_path / "t.jsonl"
    body = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Viral editing mastery: use jump cuts every 1.5 seconds, "
                        "place captions in the top third, and export 1080x1920 H.264 "
                        "for TikTok and Instagram Reels with 40% higher retention."
                    ),
                }
            ],
        },
    }
    transcript.write_bytes((json.dumps(body) + "\r\n").encode("utf-8"))

    out = run(
        project_id,
        "remember this",
        transcript_path=transcript,
        plugin_root=plugin_inbox,
    )
    assert out.get("written", 0) >= 1


@pytest.fixture
def plugin_inbox(tmp_path, monkeypatch):
    root = tmp_path / "plugin"
    (root / "inbox").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    return root


def test_backfill_script_paths_expanduser(tmp_path, monkeypatch):
    """Backfill resolves user paths on all platforms."""
    art = tmp_path / "nested" / "plan.md"
    art.parent.mkdir(parents=True)
    art.write_text("# Plan\n\n" + ("bullet fact with enough length here.\n" * 20), encoding="utf-8")

    project_id = "xplat_backfill"
    db = tmp_path / "ainl_memory.db"
    _bind_store(monkeypatch, project_id, db)

    from fact_extraction import extract_facts_from_markdown_file
    from knowledge_writer import ingest_facts, open_store

    facts = extract_facts_from_markdown_file(art.read_text(encoding="utf-8"), art.name)
    store = open_store(project_id)
    r = ingest_facts(
        project_id,
        facts,
        source_kind="backfill",
        source_ref=str(art),
        store=store,
    )
    assert r.get("written", 0) >= 1
