#!/usr/bin/env python3
"""
Backfill content-knowledge semantic facts from markdown artifacts and reference_*.md.

Usage:
  python scripts/backfill_knowledge.py --project-id <id> [--dry-run]
  python scripts/backfill_knowledge.py --cwd ~/Downloads --project-id <id>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "mcp_server"))
sys.path.insert(0, str(PLUGIN_ROOT / "hooks"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill graph knowledge from .md files")
    parser.add_argument("--project-id", required=True, help="Claude project memory bucket id")
    parser.add_argument(
        "--cwd",
        default=str(Path.home()),
        help="Working directory used to resolve project_id when omitted",
    )
    parser.add_argument(
        "--paths",
        nargs="*",
        default=[],
        help="Extra .md files or directories to ingest",
    )
    parser.add_argument(
        "--include-reference-memory",
        action="store_true",
        help="Also ingest ~/.claude/projects/*/memory/reference_*.md",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print actions only")
    args = parser.parse_args()

    from artifact_ingest import read_artifact_text
    from claude_memory_bridge import run as bridge_run
    from fact_extraction import extract_facts_from_markdown_file
    from knowledge_config import artifact_cfg, is_ingestible_artifact_path
    from knowledge_writer import ingest_facts, open_store

    targets: list[Path] = []
    for raw in args.paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            targets.extend(sorted(p.glob("**/*.md")))
        elif p.is_file():
            targets.append(p)

    downloads = Path.home() / "Downloads"
    if downloads.is_dir():
        for name in (
            "AINL_Craigcast_Clipping_Game_Plan.md",
            "2026_Viral_Video_Editing_Mastery.md",
            "2026_Social_Media_Algorithm_Mastery.md",
        ):
            candidate = downloads / name
            if candidate.is_file():
                targets.append(candidate)

    seen: set = set()
    unique_targets = []
    for t in targets:
        key = str(t.resolve()) if t.exists() else str(t)
        if key in seen:
            continue
        seen.add(key)
        if is_ingestible_artifact_path(str(t)):
            unique_targets.append(t)

    print(f"Project: {args.project_id}")
    print(f"Artifacts to ingest: {len(unique_targets)}")
    for t in unique_targets:
        print(f"  - {t}")

    if args.dry_run:
        print("Dry run — no writes.")
        return 0

    store = open_store(args.project_id)
    total = 0
    max_bytes = int(artifact_cfg().get("max_file_bytes", 512_000))

    for path in unique_targets:
        text = read_artifact_text(path, max_bytes)
        if not text:
            continue
        facts = extract_facts_from_markdown_file(text, path.name)
        if not facts:
            continue
        r = ingest_facts(
            args.project_id,
            facts,
            source_kind="backfill",
            source_ref=str(path),
            tags=["backfill", "artifact"],
            store=store,
        )
        total += r.get("written", 0) + r.get("bumped", 0)
        print(f"Ingested {path.name}: written={r.get('written')} bumped={r.get('bumped')}")

    if args.include_reference_memory:
        br = bridge_run(args.project_id, cwd=Path(args.cwd), force=True)
        print(f"Claude memory bridge: {br}")

    print(f"Done. Total fact writes/bumps: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
