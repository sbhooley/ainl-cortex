"""Windows-specific compatibility (runs on all platforms with mocks)."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from hooks.shared import a2a_log
from mcp_server.platform_paths import hook_python_invocation, venv_bin_dir


def test_a2a_log_append_without_fcntl(tmp_path):
    root = tmp_path / "plugin"
    root.mkdir()
    a2a_log.append_log(root, "IN", "a", "b", "t1", "normal", "hello")
    log = root / "a2a" / "logs" / "a2a.log"
    assert log.is_file()
    assert "hello" in log.read_text(encoding="utf-8")


def test_hook_python_invocation_windows():
    with patch("mcp_server.platform_paths.is_windows", return_value=True):
        assert hook_python_invocation() == "py -3"


def test_hook_python_invocation_unix():
    with patch("mcp_server.platform_paths.is_windows", return_value=False):
        assert hook_python_invocation() == "python3"


@pytest.fixture
def startup_mod(monkeypatch):
    """Import hooks.startup without a broken optional ainl_native wheel."""
    import builtins
    import importlib

    real_import = builtins.__import__

    def _block_ainl_native(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "ainl_native":
            raise ImportError("blocked for test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _block_ainl_native)
    for mod in list(sys.modules):
        if mod == "hooks.startup" or mod.startswith("hooks."):
            del sys.modules[mod]
    return importlib.import_module("hooks.startup")


def test_append_venv_envfile_uses_scripts_on_windows(tmp_path, monkeypatch, startup_mod):
    startup = startup_mod
    plugin = tmp_path / "plugin"
    (plugin / "hooks").mkdir(parents=True)
    (plugin / "hooks" / "startup.py").write_text("", encoding="utf-8")
    bindir = plugin / ".venv" / "Scripts"
    bindir.mkdir(parents=True)

    env_file = tmp_path / "session.env"
    monkeypatch.setenv("CLAUDE_ENV_FILE", str(env_file))

    with patch("mcp_server.platform_paths.is_windows", return_value=True):
        status = startup.append_venv_to_envfile(plugin)

    assert "appended" in status
    body = env_file.read_text(encoding="utf-8")
    assert ".venv/Scripts" in body or ".venv\\Scripts" in body.replace("\\", "/")
    assert "/bin" not in body.split("PATH=")[1].split("\n")[0]


def test_plugin_root_safe_skips_windows_temp(tmp_path, startup_mod):
    startup = startup_mod
    fake = tmp_path / "Temp" / "ainl-cortex-fresh-verify"
    fake.mkdir(parents=True)
    (fake / "hooks").mkdir()
    (fake / "hooks" / "startup.py").write_text("", encoding="utf-8")
    assert startup._plugin_root_safe_for_env(fake) is False
