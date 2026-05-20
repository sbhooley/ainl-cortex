"""Agent-visible install hints."""

from pathlib import Path
from unittest.mock import patch

from mcp_server.install_agent_hint import build_agent_install_banner


def test_banner_when_needs_install(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "startup.py").write_text("", encoding="utf-8")
    with patch("mcp_server.install_agent_hint.needs_install", return_value=True):
        with patch("mcp_server.install_agent_hint.setup_ps1_is_current", return_value=True):
            with patch("mcp_server.install_agent_hint.is_windows", return_value=True):
                text = build_agent_install_banner(tmp_path, mcp_ok=False)
    assert "AGENT INSTALL" in text
    assert "setup.cmd" in text
    assert "Do NOT" in text


def test_banner_empty_when_healthy(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    with patch("mcp_server.install_agent_hint.needs_install", return_value=False):
        with patch("mcp_server.install_agent_hint.setup_ps1_is_current", return_value=True):
            text = build_agent_install_banner(tmp_path, mcp_ok=True)
    assert text == ""
