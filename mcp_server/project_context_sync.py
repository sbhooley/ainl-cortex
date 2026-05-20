"""Hash-gated import of AGENTS.md / CLAUDE.md into semantic graph nodes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_GLOBS = ("AGENTS.md", "CLAUDE.md")
MAX_EXCERPT = 2000


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sync_project_docs(
    store,
    project_id: str,
    repo_root: Path,
    *,
    globs: Optional[List[str]] = None,
    state_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Upsert semantic nodes when project doc hashes change."""
    globs = list(globs or DEFAULT_GLOBS)
    state_path = state_path or (
        Path.home() / ".claude" / "projects" / project_id / "graph_memory" / "project_doc_hashes.json"
    )
    prev: Dict[str, str] = {}
    if state_path.exists():
        try:
            prev = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            prev = {}

    updated = 0
    current: Dict[str, str] = dict(prev)
    for name in globs:
        path = repo_root / name
        if not path.is_file():
            continue
        h = _file_hash(path)
        key = str(path)
        if prev.get(key) == h:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:MAX_EXCERPT]
            from node_types import create_semantic_node

            node = create_semantic_node(
                project_id=project_id,
                fact=f"Project conventions ({name}):\n{text}",
                confidence=0.95,
                tags=["project_doc", name],
            )
            node.data["content_hash"] = h
            node.data["source_path"] = key
            store.write_node(node)
            current[key] = h
            updated += 1
        except Exception:
            continue

    if updated:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(current, indent=2), encoding="utf-8")

    return {"updated": updated, "tracked_files": len(current)}
