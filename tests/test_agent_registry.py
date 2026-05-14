"""Tests for the local Claude Code agent registry and mailbox system."""

import json
import os
import time
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from hooks.shared.agent_registry import (
    get_agent_name,
    register_self,
    deregister_self,
    list_live_agents,
    is_local_agent,
    write_message,
    drain_mailbox,
    peek_mailbox,
)


@pytest.fixture
def plugin_root(tmp_path):
    return tmp_path


# ── Name resolution ────────────────────────────────────────────────────────


def test_env_var_overrides_auto_derive(plugin_root):
    with patch.dict(os.environ, {"AINL_AGENT_NAME": "my-worker"}):
        assert get_agent_name() == "my-worker"


def test_env_var_is_sanitised(plugin_root):
    with patch.dict(os.environ, {"AINL_AGENT_NAME": "My Agent Name!"}):
        name = get_agent_name()
        assert name == "my-agent-name"  # spaces/! become dashes, trailing dashes stripped
        assert all(c.isalnum() or c == "-" for c in name)


def test_no_env_var_falls_back_to_default(plugin_root):
    env = {k: v for k, v in os.environ.items() if k != "AINL_AGENT_NAME"}
    with patch.dict(os.environ, env, clear=True):
        with patch("hooks.shared.agent_registry._git_repo_slug", return_value=None):
            assert get_agent_name() == "claude-default"


def test_git_slug_used_when_no_env_var():
    env = {k: v for k, v in os.environ.items() if k != "AINL_AGENT_NAME"}
    with patch.dict(os.environ, env, clear=True):
        with patch("hooks.shared.agent_registry._git_repo_slug", return_value="myrepo"):
            assert get_agent_name() == "claude-myrepo"


# ── Registry ───────────────────────────────────────────────────────────────


def test_register_creates_file(plugin_root):
    register_self(plugin_root, "test-agent")
    f = plugin_root / "registry" / "test-agent.json"
    assert f.exists()
    data = json.loads(f.read_text())
    assert data["name"] == "test-agent"
    assert data["pid"] > 0  # _find_claude_pid() walks up to the long-lived parent process
    assert data["type"] == "claude-code"


def test_register_is_idempotent(plugin_root):
    register_self(plugin_root, "test-agent")
    register_self(plugin_root, "test-agent")
    files = list((plugin_root / "registry").glob("*.json"))
    assert len(files) == 1


def test_deregister_removes_file(plugin_root):
    register_self(plugin_root, "test-agent")
    deregister_self(plugin_root, "test-agent")
    assert not (plugin_root / "registry" / "test-agent.json").exists()


def test_deregister_missing_file_is_noop(plugin_root):
    deregister_self(plugin_root, "nonexistent")  # must not raise


def test_is_local_agent_true_for_live(plugin_root):
    register_self(plugin_root, "live-agent")
    assert is_local_agent(plugin_root, "live-agent") is True


def test_is_local_agent_false_when_not_registered(plugin_root):
    assert is_local_agent(plugin_root, "ghost") is False


def test_is_local_agent_false_for_dead_pid(plugin_root, tmp_path):
    # Write a registry entry with a PID that's definitely dead
    f = plugin_root / "registry" / "dead-agent.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"name": "dead-agent", "pid": 999999999, "type": "claude-code"}))
    assert is_local_agent(plugin_root, "dead-agent") is False


def test_list_live_agents_returns_only_alive(plugin_root):
    register_self(plugin_root, "alive")
    # Plant a stale entry
    dead_file = plugin_root / "registry" / "dead.json"
    dead_file.parent.mkdir(parents=True, exist_ok=True)
    dead_file.write_text(json.dumps({"name": "dead", "pid": 999999999, "type": "claude-code"}))

    agents = list_live_agents(plugin_root, cleanup_stale=True)
    names = [a["name"] for a in agents]
    assert "alive" in names
    assert "dead" not in names
    assert not dead_file.exists()  # stale entry was cleaned up


def test_list_live_agents_no_cleanup(plugin_root):
    dead_file = plugin_root / "registry" / "dead.json"
    dead_file.parent.mkdir(parents=True, exist_ok=True)
    dead_file.write_text(json.dumps({"name": "dead", "pid": 999999999, "type": "claude-code"}))

    list_live_agents(plugin_root, cleanup_stale=False)
    assert dead_file.exists()  # not cleaned up


# ── Mailbox ────────────────────────────────────────────────────────────────


def test_write_message_creates_file(plugin_root):
    msg_id = write_message(plugin_root, "target", "hello world", "sender")
    mbox = plugin_root / "mailboxes" / "target"
    files = list(mbox.glob("*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["message"] == "hello world"
    assert data["from"] == "sender"
    assert data["to"] == "target"
    assert data["id"] == msg_id


def test_write_message_respects_urgency(plugin_root):
    write_message(plugin_root, "target", "urgent!", "sender", urgency="critical")
    mbox = plugin_root / "mailboxes" / "target"
    data = json.loads(list(mbox.glob("*.json"))[0].read_text())
    assert data["urgency"] == "critical"


def test_drain_mailbox_returns_and_deletes(plugin_root):
    write_message(plugin_root, "target", "msg1", "sender")
    write_message(plugin_root, "target", "msg2", "sender")
    msgs = drain_mailbox(plugin_root, "target")
    assert len(msgs) == 2
    # Mailbox should be empty after drain
    assert drain_mailbox(plugin_root, "target") == []


def test_drain_mailbox_urgency_ordering(plugin_root):
    write_message(plugin_root, "target", "low msg", "s", urgency="low")
    write_message(plugin_root, "target", "critical msg", "s", urgency="critical")
    write_message(plugin_root, "target", "normal msg", "s", urgency="normal")
    msgs = drain_mailbox(plugin_root, "target")
    urgencies = [m["urgency"] for m in msgs]
    assert urgencies[0] == "critical"
    assert urgencies[-1] == "low"


def test_drain_mailbox_drops_expired(plugin_root):
    mbox = plugin_root / "mailboxes" / "target"
    mbox.mkdir(parents=True, exist_ok=True)
    old_msg = {
        "id": str(uuid.uuid4()), "from": "s", "to": "target",
        "message": "old", "urgency": "normal",
        "thread_id": str(uuid.uuid4()),
        "created_at": int(time.time()) - 90000,  # older than 1 day
        "type": "local",
    }
    (mbox / f"{old_msg['id']}.json").write_text(json.dumps(old_msg))
    msgs = drain_mailbox(plugin_root, "target", max_age_seconds=86400)
    assert msgs == []


def test_drain_empty_mailbox_returns_empty(plugin_root):
    assert drain_mailbox(plugin_root, "nobody") == []


def test_peek_mailbox_count(plugin_root):
    assert peek_mailbox(plugin_root, "target") == 0
    write_message(plugin_root, "target", "a", "s")
    write_message(plugin_root, "target", "b", "s")
    assert peek_mailbox(plugin_root, "target") == 2
    drain_mailbox(plugin_root, "target")
    assert peek_mailbox(plugin_root, "target") == 0


# ── Routing integration ────────────────────────────────────────────────────


def test_send_and_receive_between_two_agents(plugin_root):
    """Simulate two Claude instances exchanging a message via the shared mailbox."""
    # Instance A registers itself
    register_self(plugin_root, "agent-a")
    # Instance B registers itself
    register_self(plugin_root, "agent-b")

    # A checks that B is local and reachable
    assert is_local_agent(plugin_root, "agent-b")

    # A sends a message to B
    write_message(plugin_root, "agent-b", "task complete", "agent-a", urgency="normal")

    # B drains its mailbox
    msgs = drain_mailbox(plugin_root, "agent-b")
    assert len(msgs) == 1
    assert msgs[0]["message"] == "task complete"
    assert msgs[0]["from"] == "agent-a"

    # Cleanup
    deregister_self(plugin_root, "agent-a")
    deregister_self(plugin_root, "agent-b")
    assert not is_local_agent(plugin_root, "agent-a")
    assert not is_local_agent(plugin_root, "agent-b")
