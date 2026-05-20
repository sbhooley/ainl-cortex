"""Cross-platform venv path resolution."""

import json
import sys
from pathlib import Path

import pytest

from mcp_server.platform_paths import (
    hook_command,
    os_family,
    read_install_manifest,
    venv_bin_dir,
    venv_python,
    write_install_manifest,
)


def test_os_family_is_known():
    assert os_family() in ("windows", "darwin", "linux", "other")


def test_venv_bin_dir_layout():
    root = Path("/tmp/ainl-cortex-test")
    if sys.platform == "win32":
        assert venv_bin_dir(root).as_posix().endswith(".venv/Scripts")
    else:
        assert venv_bin_dir(root).as_posix().endswith(".venv/bin")


def test_hook_command_uses_run_hook_not_bin_python(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    cmd = hook_command("startup", tmp_path)
    assert "run_hook.py" in cmd
    assert "startup" in cmd
    assert ".venv/bin/python" not in cmd
    assert "Scripts" not in cmd or sys.platform == "win32"


def test_write_install_manifest_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    bindir = venv_bin_dir(tmp_path)
    bindir.mkdir(parents=True)
    fake_py = bindir / ("python.exe" if sys.platform == "win32" else "python3")
    fake_py.write_text("", encoding="utf-8")
    write_install_manifest(tmp_path, test_flag=True)
    data = read_install_manifest(tmp_path)
    assert data is not None
    assert data.get("platform") == os_family()
    assert data.get("test_flag") is True
