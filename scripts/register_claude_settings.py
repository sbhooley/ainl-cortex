#!/usr/bin/env python3
"""Merge ainl-local marketplace + enabled plugin into ~/.claude/settings.json."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def register(settings_path: Path, marketplace_path: Path) -> None:
    settings: dict = {}
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            print(f"WARNING: could not parse {settings_path}, creating fresh", file=sys.stderr)

    settings.setdefault("extraKnownMarketplaces", {})["ainl-local"] = {
        "source": {"source": "directory", "path": str(marketplace_path.resolve())}
    }
    settings.setdefault("enabledPlugins", {})["ainl-cortex@ainl-local"] = True

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    print(f"  {settings_path} updated")

    try:
        from scripts.sync_installed_plugins import sync_installed_plugins

        link = marketplace_path / "plugins" / "ainl-cortex"
        plugin_dir = link.resolve() if link.exists() else link
        _changed, _msg = sync_installed_plugins(plugin_dir)
        if _changed:
            print(f"  installed_plugins.json: {_msg}")
    except Exception as exc:
        print(f"  WARNING: installed_plugins sync skipped: {exc}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "settings",
        nargs="?",
        type=Path,
        default=Path.home() / ".claude" / "settings.json",
    )
    ap.add_argument(
        "marketplace",
        nargs="?",
        type=Path,
        default=Path.home() / ".claude" / "ainl-local-marketplace",
    )
    args = ap.parse_args()
    register(args.settings, args.marketplace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
