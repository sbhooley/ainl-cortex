"""Python bootstrap (uv) helpers."""

from pathlib import Path
from unittest.mock import patch

from mcp_server.python_bootstrap import (
    _uv_release_asset,
    bootstrap_enabled,
    bootstrap_python,
)


def test_bootstrap_enabled_env():
    with patch.dict("os.environ", {"AINL_CORTEX_SKIP_PYTHON_BOOTSTRAP": "1"}):
        assert bootstrap_enabled() is False


def test_uv_release_asset_names():
    asset = _uv_release_asset()
    assert asset.startswith("uv-")
    assert "uv" in asset


def test_bootstrap_skips_when_python_present(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "startup.py").write_text("", encoding="utf-8")
    fake_py = tmp_path / "fake.py"
    fake_py.write_text("print(1)", encoding="utf-8")
    with patch("mcp_server.python_bootstrap.find_system_python", return_value=fake_py):
        with patch("mcp_server.python_bootstrap.venv_python", return_value=None):
            ok, msg = bootstrap_python(tmp_path, force=True)
    assert ok is True
    assert "available" in msg.lower() or "system" in msg.lower()
