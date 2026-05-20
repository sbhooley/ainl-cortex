"""Tests for claude_integration_heal."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_server.claude_integration_heal import (
    format_heal_banner,
    installed_plugins_needs_sync,
    mcp_launcher_needs_update,
)


def test_mcp_launcher_needs_update_detects_python_command(tmp_path):
    plugin = tmp_path / "ainl-cortex"
    plugin.mkdir()
    manifest_dir = plugin / ".claude-plugin"
    manifest_dir.mkdir()
    (manifest_dir / "plugin.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "ainl-cortex": {
                        "command": "python",
                        "args": ["${CLAUDE_PLUGIN_ROOT}/mcp_launch.py"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    need, reason = mcp_launcher_needs_update(plugin)
    assert need is True
    assert "python3" in reason or "command" in reason


def test_installed_plugins_needs_sync_stale_cache(tmp_path, monkeypatch):
    plugin = tmp_path / "live"
    plugin.mkdir()
    claude = tmp_path / ".claude" / "plugins"
    claude.mkdir(parents=True)
    ip = claude / "installed_plugins.json"
    stale = str(tmp_path / "cache" / "ainl-cortex" / "0.2.0")
    ip.write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "ainl-cortex@ainl-local": [{"installPath": stale, "scope": "user"}]
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "mcp_server.claude_integration_heal._installed_plugins_path",
        lambda: ip,
    )
    need, reason = installed_plugins_needs_sync(plugin)
    assert need is True
    assert "mismatch" in reason or "cache" in reason


def test_format_heal_banner_reload_hint():
    text = format_heal_banner(True, ["installed_plugins: fixed"])
    assert "AUTO-HEAL" in text
    assert "/reload-plugins" in text


def test_canonical_plugin_root_prefers_live_over_cache(tmp_path, monkeypatch):
    cache = tmp_path / "cache" / "ainl-cortex" / "0.2.0"
    live = tmp_path / "live" / "ainl-cortex"
    for root in (cache, live):
        root.mkdir(parents=True)
        (root / "hooks").mkdir()
        (root / "hooks" / "startup.py").write_text("# hook", encoding="utf-8")
        manifest = root / ".claude-plugin"
        manifest.mkdir()
        ver = "0.2.0" if root == cache else "0.4.0"
        (manifest / "plugin.json").write_text(
            json.dumps({"version": ver}),
            encoding="utf-8",
        )

    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(cache))
    from mcp_server.platform_paths import canonical_plugin_root

    # Simulate standard live path by patching home
    monkeypatch.setattr(
        "mcp_server.platform_paths.Path.home",
        lambda: tmp_path / "home",
    )
    standard = tmp_path / "home" / ".claude" / "plugins" / "ainl-cortex"
    standard.parent.mkdir(parents=True)
    import shutil

    shutil.copytree(live, standard)

    got = canonical_plugin_root()
    assert got.resolve() == standard.resolve()
