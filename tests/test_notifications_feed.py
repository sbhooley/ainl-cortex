"""Unit tests for hooks/notifications.py (product feed contract)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS))

import notifications as N  # noqa: E402


def test_version_in_range_bounds():
    assert N._version_in_range("0.2.5", "0.2.0", "0.2.99") is True
    assert N._version_in_range("0.1.9", "0.2.0", "0.2.99") is False
    assert N._version_in_range("0.3.0", "0.2.0", "0.2.99") is False
    assert N._version_in_range("0.2.0", None, None) is True


def test_targets_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = {"notifications": {"enabled": True, "url": "http://example.invalid", "check_timeout_seconds": 1.0}}

    payload = {
        "schema_version": 1,
        "notifications": [
            {
                "id": "n-cortex",
                "title": "Cortex only",
                "body": "x",
                "severity": "info",
                "targets": ["claude-code-plugin"],
                "published_at": "2026-05-12T00:00:00Z",
            },
            {
                "id": "n-wild",
                "title": "Wildcard",
                "body": "y",
                "severity": "warning",
                "targets": ["*"],
                "published_at": "2026-05-11T00:00:00Z",
                "priority": 5,
            },
            {
                "id": "n-armaraos",
                "title": "Wrong target",
                "body": "z",
                "severity": "info",
                "targets": ["armaraos-desktop"],
                "published_at": "2026-05-13T00:00:00Z",
            },
        ],
    }

    def fake_fetch(url: str, version: str, timeout: float):
        assert "example.invalid" in url
        return payload

    monkeypatch.setattr(N, "_fetch", fake_fetch)

    new, _msgs = N.poll(tmp_path, cfg)
    ids = {n["id"] for n in new}
    assert "n-cortex" in ids
    assert "n-wild" in ids
    assert "n-armaraos" not in ids


def test_expires_at_drops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = {"notifications": {"enabled": True, "url": "http://example.invalid", "check_timeout_seconds": 1.0}}
    payload = {
        "schema_version": 1,
        "notifications": [
            {
                "id": "n-old",
                "title": "Expired",
                "body": "",
                "severity": "info",
                "targets": ["claude-code-plugin"],
                "published_at": "2020-01-01T00:00:00Z",
                "expires_at": "2020-02-01T00:00:00Z",
            },
            {
                "id": "n-fresh",
                "title": "Fresh",
                "body": "",
                "severity": "info",
                "targets": ["claude-code-plugin"],
                "published_at": "2026-05-12T00:00:00Z",
            },
        ],
    }
    monkeypatch.setattr(N, "_fetch", lambda *a, **k: payload)
    new, _ = N.poll(tmp_path, cfg)
    assert [n["id"] for n in new] == ["n-fresh"]


def test_seen_persistence_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = {"notifications": {"enabled": True, "url": "http://example.invalid", "check_timeout_seconds": 1.0}}
    payload = {
        "schema_version": 1,
        "notifications": [
            {
                "id": "n-once",
                "title": "Once",
                "body": "",
                "severity": "info",
                "targets": ["claude-code-plugin"],
                "published_at": "2026-05-12T00:00:00Z",
            }
        ],
    }
    monkeypatch.setattr(N, "_fetch", lambda *a, **k: payload)

    a, _ = N.poll(tmp_path, cfg)
    assert len(a) == 1

    b, _ = N.poll(tmp_path, cfg)
    assert b == []

    seen_path = tmp_path / N.SEEN_FILE_REL
    assert seen_path.exists()
    data = json.loads(seen_path.read_text())
    assert "n-once" in data.get("seen_ids", [])
