"""Install bootstrap helpers."""

from pathlib import Path
from unittest.mock import patch

from mcp_server.install_bootstrap import is_safe_install_root, needs_install


def test_is_safe_install_root_rejects_temp(tmp_path):
    fake = tmp_path / "Temp" / "ainl-cortex-fresh"
    fake.mkdir(parents=True)
    (fake / "hooks").mkdir()
    (fake / "hooks" / "startup.py").write_text("", encoding="utf-8")
    assert is_safe_install_root(fake) is False


def test_is_safe_install_root_accepts_real_layout(tmp_path):
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "startup.py").write_text("", encoding="utf-8")
    assert is_safe_install_root(tmp_path) is True


def test_needs_install_without_venv(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    (tmp_path / "hooks").mkdir()
    assert needs_install(tmp_path) is True
