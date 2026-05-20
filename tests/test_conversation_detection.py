"""Tests aligned with armara-provider-api conversation_detection.rs."""

from __future__ import annotations

import os

import pytest

from hooks.shared.conversation_detection import (
    has_action_intent,
    is_conversation_only_messages,
    is_conversation_only_turn,
    is_short_ack_or_ping_for_tool_latch,
)


def test_stock_price_question_is_action_intent():
    assert has_action_intent("What is the price of Apple stock today?")
    assert has_action_intent("What's AAPL trading at?")


def test_greetings_stay_conversation_only():
    assert not has_action_intent("Hello")
    assert not has_action_intent("How are you?")


def test_stock_photo_not_financial_lookup():
    assert not has_action_intent("I need a stock photo of a tree")


def test_long_creative_prompt_not_automatic_action():
    s = (
        "You are the worlds greatest branding expert — You go into a house, "
        "and you video what the house looks like now, and on a split screen "
        "of the same video you show what it could look like if the house was upgraded"
    )
    assert not has_action_intent(s)


def test_narrative_show_vs_show_me():
    assert not has_action_intent("On the left you show the before and on the right the after.")
    assert has_action_intent("Please show the logs from the last deploy.")
    assert has_action_intent("Can you show me the file at ./src/main.rs?")


def test_browser_navigate_without_scheme():
    assert has_action_intent("can you use the browser to navigate to zerabook.ai")
    assert has_action_intent("navigate to example.com for me")
    assert not has_action_intent("we talked about the browser wars in the 90s")


def test_browse_web_save_file():
    assert has_action_intent(
        "Can you browse the web and get me all the latest social media trends "
        "online and save them to a file?"
    )


def test_latch_short_followup_after_action():
    msgs = [
        ("user", "run ./hello.ainl and summarize errors"),
        ("assistant", "[no response]"),
        ("user", "Please provide your response."),
    ]
    assert not is_conversation_only_messages(msgs)


def test_latch_does_not_keep_tools_for_thanks_after_old_work():
    msgs = [
        ("user", "run ./hello.ainl"),
        ("assistant", "Done."),
        ("user", "thanks"),
    ]
    assert is_conversation_only_messages(msgs)


def test_conversation_only_thanks_ok():
    assert is_conversation_only_turn("thanks")
    assert is_conversation_only_turn("ok")


def test_action_fix_bug():
    assert not is_conversation_only_turn("fix the bug in auth.py")


def test_force_action_intent_env(monkeypatch):
    monkeypatch.setenv("AINL_CORTEX_FORCE_ACTION_INTENT", "1")
    assert not is_conversation_only_turn("thanks")


def test_disable_detection_env(monkeypatch):
    monkeypatch.setenv("AINL_CORTEX_DISABLE_CONVERSATION_DETECTION", "1")
    assert not is_conversation_only_turn("thanks")


def test_short_ack_ping_helper():
    assert is_short_ack_or_ping_for_tool_latch("ok")
    assert not is_short_ack_or_ping_for_tool_latch("x" * 60)
