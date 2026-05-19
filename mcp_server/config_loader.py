"""
Merge tracked config.json with gitignored config.local.json (machine-only keys).

Load order: config.json, then config.local.json (deep merge; local wins).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

LOCAL_CONFIG_FILENAME = "config.local.json"
LOCAL_ONLY_TOP_LEVEL_KEYS = frozenset({"install_id"})


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base (override wins for scalars/lists)."""
    out = dict(base)
    for key, val in override.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(val, dict)
        ):
            out[key] = deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def _read_json_object(path: Path) -> dict:
    try:
        loaded = json.loads(path.read_text())
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def load_config_files(plugin_root: Path) -> dict:
    """Merge config.json and config.local.json from plugin_root."""
    merged: dict = {}
    for name in ("config.json", LOCAL_CONFIG_FILENAME):
        path = plugin_root / name
        if path.is_file():
            loaded = _read_json_object(path)
            if loaded:
                merged = deep_merge(merged, loaded)
    return merged


def migrate_install_id_to_local(plugin_root: Path) -> bool:
    """Move install_id from config.json into config.local.json if present."""
    main_path = plugin_root / "config.json"
    local_path = plugin_root / LOCAL_CONFIG_FILENAME
    if not main_path.is_file():
        return False

    cfg = _read_json_object(main_path)
    install_id = cfg.pop("install_id", None)
    if not install_id:
        return False

    local_cfg = _read_json_object(local_path) if local_path.is_file() else {}
    local_cfg.setdefault("install_id", install_id)

    with open(main_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    with open(local_path, "w", encoding="utf-8") as f:
        json.dump(local_cfg, f, indent=2)
        f.write("\n")
    return True


def write_local_config(plugin_root: Path, local_payload: dict) -> None:
    """Persist machine-only keys to config.local.json."""
    local_path = plugin_root / LOCAL_CONFIG_FILENAME
    local_path.parent.mkdir(parents=True, exist_ok=True)
    with open(local_path, "w", encoding="utf-8") as f:
        json.dump(local_payload, f, indent=2)
        f.write("\n")


def split_merged_config(merged: dict) -> tuple[dict, dict]:
    """Split merged config into tracked main vs local-only payloads."""
    main = {k: v for k, v in merged.items() if k not in LOCAL_ONLY_TOP_LEVEL_KEYS}
    local = {k: v for k, v in merged.items() if k in LOCAL_ONLY_TOP_LEVEL_KEYS}
    return main, local
