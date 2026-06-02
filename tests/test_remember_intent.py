"""Remember-this store intent vs recall intent."""

from __future__ import annotations

from hooks.shared.conversation_detection import (
    has_action_intent,
    implies_memory_recall_intent,
    implies_memory_store_intent,
    is_conversation_only_turn,
)


def test_remember_this_is_store_not_recall():
    assert implies_memory_store_intent("remember this in graph memory")
    assert not implies_memory_recall_intent("remember this in graph memory")
    assert has_action_intent("remember this in graph memory")
    assert not is_conversation_only_turn("remember this in graph memory")


def test_do_you_remember_stays_recall():
    assert not implies_memory_store_intent("do you remember the clipping plan?")
    assert implies_memory_recall_intent("do you remember the clipping plan?")


def test_save_to_memory_is_store():
    assert implies_memory_store_intent("please save this to graph memory")
    assert not implies_memory_recall_intent("please save this to graph memory")
