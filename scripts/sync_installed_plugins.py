#!/usr/bin/env python3
"""
Point Claude Code's installed_plugins.json at the live plugin directory.

After ``git clone`` to ~/.claude/plugins/ainl-cortex, Claude may still load a
stale ``plugins/cache/ainl-local/ainl-cortex/<old-version>`` path from an earlier
marketplace install — SessionStart hooks then never run from the new tree.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PLUGIN_KEY = "ainl-cortex@ainl-local"
LEGACY_KEYS = ("ainl-graph-memory@ainl-local",)


def _git_sha(plugin_dir: Path) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(plugin_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return out.stdout.strip() or None
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        return None


def _plugin_version(plugin_dir: Path) -> str:
    manifest = plugin_dir / ".claude-plugin" / "plugin.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            ver = data.get("version")
            if isinstance(ver, str) and ver.strip():
                return ver.strip()
        except (json.JSONDecodeError, OSError):
            pass
    return "0.0.0"


def sync_installed_plugins(
    plugin_dir: Path,
    *,
    installed_plugins_path: Optional[Path] = None,
    scope: str = "user",
    remove_legacy: bool = True,
) -> tuple[bool, str]:
    """
    Update ``~/.claude/plugins/installed_plugins.json`` installPath for ainl-cortex.

    Returns (changed, message).
    """
    plugin_dir = plugin_dir.resolve()
    path = installed_plugins_path or (Path.home() / ".claude" / "plugins" / "installed_plugins.json")

    payload: Dict[str, Any] = {"version": 2, "plugins": {}}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {"version": 2, "plugins": {}}
    if not isinstance(payload.get("plugins"), dict):
        payload["plugins"] = {}

    plugins: Dict[str, Any] = payload["plugins"]
    if remove_legacy:
        for key in LEGACY_KEYS:
            plugins.pop(key, None)

    version = _plugin_version(plugin_dir)
    sha = _git_sha(plugin_dir)
    now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    entry = {
        "scope": scope,
        "installPath": str(plugin_dir),
        "version": version,
        "installedAt": now,
        "lastUpdated": now,
    }
    if sha:
        entry["gitCommitSha"] = sha

    prev_list = plugins.get(PLUGIN_KEY)
    prev_path = None
    if isinstance(prev_list, list) and prev_list and isinstance(prev_list[0], dict):
        prev_path = prev_list[0].get("installPath")

    plugins[PLUGIN_KEY] = [entry]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if prev_path == str(plugin_dir):
        return False, f"already pointed at {plugin_dir}"
    if prev_path:
        return True, f"installPath {prev_path} → {plugin_dir}"
    return True, f"registered installPath {plugin_dir}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--plugin-dir",
        type=Path,
        default=ROOT,
        help="AINL Cortex plugin root (default: repo root)",
    )
    ap.add_argument(
        "--installed-plugins",
        type=Path,
        default=Path.home() / ".claude" / "plugins" / "installed_plugins.json",
    )
    args = ap.parse_args(argv)
    changed, msg = sync_installed_plugins(
        args.plugin_dir,
        installed_plugins_path=args.installed_plugins,
    )
    print(f"  [{'ok' if changed else 'ok'}] installed_plugins.json: {msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
