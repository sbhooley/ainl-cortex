#!/usr/bin/env python3
"""Create ~/.claude/ainl-local-marketplace and link this plugin into it."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_server.platform_paths import is_windows  # noqa: E402

MARKETPLACE_NAME = "ainl-local"


def marketplace_root() -> Path:
    return Path.home() / ".claude" / "ainl-local-marketplace"


def marketplace_json_path() -> Path:
    return marketplace_root() / ".claude-plugin" / "marketplace.json"


def plugin_link_path() -> Path:
    return marketplace_root() / "plugins" / "ainl-cortex"


def _remove_link(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
        return
    if not path.exists():
        return
    if is_windows():
        try:
            subprocess.run(
                ["cmd", "/c", "rmdir", str(path)],
                check=False,
                capture_output=True,
            )
            if not path.exists():
                return
        except OSError:
            pass
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def _create_plugin_link(plugin_dir: Path, link_path: Path) -> bool:
    plugin_dir = plugin_dir.resolve()
    link_path.parent.mkdir(parents=True, exist_ok=True)
    _remove_link(link_path)

    if is_windows():
        try:
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link_path), str(plugin_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
            return link_path.exists()
        except (subprocess.CalledProcessError, OSError):
            pass
        try:
            os.symlink(plugin_dir, link_path, target_is_directory=True)
            return link_path.exists()
        except OSError:
            return False

    os.symlink(plugin_dir, link_path, target_is_directory=True)
    return link_path.is_symlink() or link_path.exists()


def write_marketplace_json() -> None:
    mp = marketplace_root()
    meta_dir = mp / ".claude-plugin"
    meta_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": MARKETPLACE_NAME,
        "version": "1.0.0",
        "description": "Local marketplace: AINL Cortex",
        "owner": {"name": "local"},
        "plugins": [
            {
                "name": "ainl-cortex",
                "description": (
                    "Graph-native memory, self-learning, and multi-agent coordination "
                    "for Claude Code"
                ),
                "source": "./plugins/ainl-cortex",
            }
        ],
    }
    marketplace_json_path().write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def ensure_local_marketplace(plugin_dir: Path) -> Path:
    """
    Ensure marketplace tree exists and ``plugins/ainl-cortex`` points at *plugin_dir*.

    Returns the marketplace directory path.
    """
    mp = marketplace_root()
    mp.mkdir(parents=True, exist_ok=True)
    write_marketplace_json()
    linked = _create_plugin_link(plugin_dir, plugin_link_path())
    if not linked:
        print(
            f"WARNING: could not junction/symlink {plugin_link_path()} → {plugin_dir}",
            file=sys.stderr,
        )
    return mp


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "plugin_dir",
        nargs="?",
        type=Path,
        default=ROOT,
        help="AINL Cortex plugin root (default: repo root)",
    )
    args = ap.parse_args(argv)
    mp = ensure_local_marketplace(args.plugin_dir.resolve())
    print(f"  [ok] marketplace: {mp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
