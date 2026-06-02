"""
Claude Code project directory naming (macOS, Linux, Windows).

Transcript and memory folders live under ``~/.claude/projects/<slug>/``.
Slugs encode the cwd by replacing path separators with hyphens.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional


def encode_claude_cwd_slug(cwd: Path) -> str:
    """
    Encode a filesystem path the way Claude Code names project folders.

    Examples:
      /Users/alice           -> -Users-alice
      C:\\Users\\alice       -> -C-Users-alice
    """
    p = cwd.expanduser()
    raw = str(p).replace("\\", "/")
    # Windows drive paths: never resolve() on Unix CI — that produces bogus slugs.
    if len(raw) >= 2 and raw[1] == ":":
        posix = raw
        if len(posix) >= 2 and posix[1] == ":":
            posix = posix[0] + posix[2:]
        enc = posix.replace("/", "-")
        if enc and not enc.startswith("-"):
            enc = "-" + enc
        return enc

    try:
        resolved = p.resolve()
    except OSError:
        resolved = p

    posix = resolved.as_posix()
    enc = posix.replace("/", "-")
    if enc and not enc.startswith("-"):
        enc = "-" + enc
    return enc


def claude_projects_root() -> Path:
    return Path.home() / ".claude" / "projects"


def candidate_claude_memory_dirs(
    cwd: Optional[Path] = None,
    *,
    memory_dir_name: str = "memory",
) -> List[Path]:
    """Ordered candidate paths for ``reference_*.md`` under Claude projects."""
    root = claude_projects_root()
    candidates: List[Path] = []

    if cwd is not None:
        slug = encode_claude_cwd_slug(cwd)
        candidates.append(root / slug / memory_dir_name)
        alt = slug if slug.startswith("-") else f"-{slug.lstrip('-')}"
        if alt != slug:
            candidates.append(root / alt / memory_dir_name)

    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / memory_dir_name).is_dir():
                p = child / memory_dir_name
                if p not in candidates:
                    candidates.append(p)

    return candidates


def normalize_transcript_path(transcript_path: str | Path) -> Path:
    """Expand user/home and accept Windows backslash paths."""
    return Path(str(transcript_path)).expanduser()
