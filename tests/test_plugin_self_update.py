"""Tests for plugin_self_update."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_server.claude_integration_heal import installed_plugins_needs_sync
from mcp_server.plugin_self_update import maybe_refresh_plugin_code


def _write_plugin(root: Path, version: str) -> None:
    (root / "hooks").mkdir(parents=True, exist_ok=True)
    (root / "hooks" / "startup.py").write_text("# hook", encoding="utf-8")
    manifest = root / ".claude-plugin"
    manifest.mkdir(exist_ok=True)
    (manifest / "plugin.json").write_text(
        json.dumps({"version": version}),
        encoding="utf-8",
    )


def test_installed_plugins_version_mismatch(tmp_path, monkeypatch):
    live = tmp_path / "live"
    live.mkdir()
    _write_plugin(live, "0.4.5")
    ip = tmp_path / "installed_plugins.json"
    ip.write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "ainl-cortex@ainl-local": [
                        {
                            "installPath": str(live),
                            "scope": "user",
                            "version": "0.4.3",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "mcp_server.claude_integration_heal._installed_plugins_path",
        lambda: ip,
    )
    need, reason = installed_plugins_needs_sync(live)
    assert need is True
    assert "0.4.3" in reason and "0.4.5" in reason


def test_maybe_refresh_prefers_standard_over_cache(tmp_path, monkeypatch):
    cache = tmp_path / ".claude" / "plugins" / "cache" / "ainl-local" / "ainl-cortex" / "0.4.3"
    standard = tmp_path / "home" / ".claude" / "plugins" / "ainl-cortex"
    for root, ver in ((cache, "0.4.3"), (standard, "0.4.5")):
        _write_plugin(root, ver)

    monkeypatch.setattr(
        "mcp_server.plugin_self_update.standard_plugin_path",
        lambda: standard,
    )
    monkeypatch.setattr(
        "mcp_server.plugin_self_update.canonical_plugin_root",
        lambda _r: standard,
    )
    monkeypatch.setattr(
        "mcp_server.plugin_self_update.is_git_repo",
        lambda _p: False,
    )

    reload, actions, effective = maybe_refresh_plugin_code(cache)
    assert effective.resolve() == standard.resolve()
    assert any("cache" in a.lower() for a in actions)
