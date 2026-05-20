"""ArmaraOS daemon cost hint bridge."""

from unittest import mock

from hooks.shared.armaraos_daemon import fetch_daemon_cost_hint


def test_fetch_daemon_cost_hint_parses_tokens_saved():
  payload = b'{"eco": {"tokens_saved": 1200}}'
  with mock.patch("urllib.request.urlopen") as urlopen:
    urlopen.return_value.__enter__.return_value.read.return_value = payload
    hint = fetch_daemon_cost_hint("http://127.0.0.1:4200")
  assert hint is not None
  assert hint.get("tokens_saved") == 1200


def test_fetch_daemon_cost_hint_unreachable_returns_none():
  with mock.patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
    assert fetch_daemon_cost_hint("http://127.0.0.1:9") is None
