"""setup.ps1 version marker (Windows install safety)."""

from pathlib import Path

from mcp_server.install_bootstrap import (
    SETUP_PS1_VERSION_MARKER,
    setup_ps1_is_current,
)


def test_setup_ps1_has_version_marker():
    root = Path(__file__).resolve().parent.parent
    text = (root / "setup.ps1").read_text(encoding="utf-8")
    assert SETUP_PS1_VERSION_MARKER in text
    assert setup_ps1_is_current(root)
