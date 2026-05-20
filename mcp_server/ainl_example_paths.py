"""Resolve strict-valid example .ainl paths for promotion stubs."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional


def resolve_example_path(example_path: str, plugin_root: Optional[Path] = None) -> Optional[Path]:
    """Find example file under plugin, installed ainativelang, or sibling checkout."""
    plugin_root = plugin_root or Path(__file__).resolve().parent.parent
    rel = example_path.lstrip("/")
    candidates: List[Path] = [
        plugin_root / rel,
    ]
    try:
        import compiler_v2  # PyPI package name: ainativelang

        pkg_root = Path(compiler_v2.__file__).resolve().parent
        candidates.append(pkg_root / rel)
    except Exception:
        pass
    for extra in (
        plugin_root.parent / "AI_Native_Lang" / rel,
        plugin_root.parent / "ainativelang" / rel,
    ):
        candidates.append(extra)
    for path in candidates:
        if path.is_file():
            return path
    return None
