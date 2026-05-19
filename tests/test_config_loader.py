"""Tests for config.json + config.local.json merge and migration."""

from __future__ import annotations

import json
from pathlib import Path

from mcp_server.config_loader import (
    LOCAL_CONFIG_FILENAME,
    load_config_files,
    migrate_install_id_to_local,
    split_merged_config,
)


def test_load_merges_local_over_main(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(
        json.dumps({"memory": {"store_backend": "python"}, "compression": {"mode": "balanced"}})
    )
    (tmp_path / LOCAL_CONFIG_FILENAME).write_text(
        json.dumps({"install_id": "local-uuid", "compression": {"mode": "aggressive"}})
    )
    merged = load_config_files(tmp_path)
    assert merged["install_id"] == "local-uuid"
    assert merged["memory"]["store_backend"] == "python"
    assert merged["compression"]["mode"] == "aggressive"


def test_migrate_install_id_moves_to_local(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(
        json.dumps({"install_id": "old-id", "memory": {"store_backend": "python"}})
    )
    assert migrate_install_id_to_local(tmp_path) is True
    main = json.loads((tmp_path / "config.json").read_text())
    local = json.loads((tmp_path / LOCAL_CONFIG_FILENAME).read_text())
    assert "install_id" not in main
    assert local["install_id"] == "old-id"


def test_split_merged_config() -> None:
    main, local = split_merged_config(
        {"install_id": "x", "memory": {"store_backend": "native"}}
    )
    assert "install_id" not in main
    assert local == {"install_id": "x"}
    assert main["memory"]["store_backend"] == "native"
