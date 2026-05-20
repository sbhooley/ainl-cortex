"""
Heuristic conversation-only vs action-intent detection.

Ported from armara-provider-api conversation_detection.rs — keep in sync with
ainl-inference-server docs/architecture/CONVERSATION_ACTION_INTENT.md
"""

from __future__ import annotations

import os
import re
from typing import List, Optional, Sequence, Tuple

ACTION_VERBS = frozenset(
    {
        "run",
        "search",
        "find",
        "read",
        "write",
        "create",
        "analyze",
        "check",
        "validate",
        "compile",
        "execute",
        "help",
        "get",
        "fetch",
        "open",
        "list",
        "delete",
        "update",
        "fix",
        "edit",
        "save",
        "make",
        "build",
        "deploy",
        "test",
        "debug",
        "navigate",
        "browse",
    }
)

SHORT_ACK_MAX_CHARS = 56
SHORT_ACK_EXACT = frozenset(
    {
        "ok",
        "okay",
        "k",
        "thanks",
        "thank you",
        "ty",
        "go ahead",
        "please respond",
        "please reply",
        "yes",
        "yep",
        "yeah",
        "sure",
        "continue",
        "sounds good",
        "do it",
        "proceed",
        "pls",
        "please",
        "go",
        "y",
    }
)


def _cleaned_alphabetic_token(word: str) -> str:
    return re.sub(r"[^a-zA-Z]", "", word)


def _has_whole_word(lower: str, needle: str) -> bool:
    return any(_cleaned_alphabetic_token(w) == needle for w in lower.split())


def implies_show_me_tool_intent(lower: str) -> bool:
    return (
        "show me" in lower
        or "please show" in lower
        or "can you show" in lower
        or "could you show" in lower
        or "show the file" in lower
        or "show the code" in lower
        or "show the output" in lower
        or "show the error" in lower
        or "show the logs" in lower
        or "show the result" in lower
    )


def implies_browser_tool_intent(lower: str) -> bool:
    if "browser" not in lower:
        return False
    return (
        "navigate" in lower
        or "open" in lower
        or "visit" in lower
        or "go to" in lower
        or "screenshot" in lower
        or "click" in lower
        or "scroll" in lower
        or _has_whole_word(lower, "browse")
    )


def implies_live_lookup_intent(lower: str) -> bool:
    if (
        "stock photo" in lower
        or "stock image" in lower
        or "stock footage" in lower
    ):
        return False

    equity_context = (
        "stock" in lower
        or "share price" in lower
        or "equity" in lower
        or "aapl" in lower
    )
    quote_signals = (
        "price" in lower
        or "quote" in lower
        or "trading" in lower
        or "worth" in lower
        or "market cap" in lower
        or "today" in lower
        or "right now" in lower
        or "currently" in lower
        or "now" in lower
    )

    if equity_context and quote_signals:
        return True

    if ("what is" in lower or "what's" in lower) and "stock" in lower:
        if "stock photo" not in lower:
            return True

    if "weather" in lower and (
        "?" in lower
        or "today" in lower
        or "tomorrow" in lower
        or "forecast" in lower
    ):
        return True

    return False


def has_action_intent(content: str) -> bool:
    """True when user text clearly asks for tool-backed work."""
    content = content.strip()
    if not content:
        return False

    lower = content.lower()
    if implies_live_lookup_intent(lower):
        return True
    if implies_show_me_tool_intent(lower):
        return True
    if implies_browser_tool_intent(lower):
        return True
    if (
        "://" in content
        or "`" in content
        or "~/" in content
        or "\\" in content
        or ".ainl" in lower
        or "mcp_" in lower
    ):
        return True

    for word in lower.split():
        cleaned = _cleaned_alphabetic_token(word)
        if cleaned in ACTION_VERBS:
            return True

    return False


def conversation_detection_enabled() -> bool:
    """Env AINL_CORTEX_DISABLE_CONVERSATION_DETECTION=1 disables heuristics."""
    v = os.environ.get("AINL_CORTEX_DISABLE_CONVERSATION_DETECTION", "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return False
    return True


def force_action_intent() -> bool:
    """Env AINL_CORTEX_FORCE_ACTION_INTENT=1 always treats turns as action-shaped."""
    v = os.environ.get("AINL_CORTEX_FORCE_ACTION_INTENT", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def normalized_ack_phrase(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^[\s\W]+|[\s\W]+$", "", t)
    return t.lower()


def is_pure_gratitude_short_ack(text: str) -> bool:
    return normalized_ack_phrase(text) in ("thanks", "thank you", "ty", "thx")


def is_short_ack_or_ping_for_tool_latch(text: str) -> bool:
    t = text.strip()
    if not t or "\n" in t:
        return False
    if len(t) > SHORT_ACK_MAX_CHARS:
        return False
    lower = t.lower()
    if normalized_ack_phrase(t) in SHORT_ACK_EXACT:
        return True
    if "please provide your response" in lower or "please provide a response" in lower:
        return True
    return len(t) <= 22


def _latest_and_previous_user_text(
    messages: Sequence[Tuple[str, str]],
) -> Optional[Tuple[str, Optional[str]]]:
    users = [c for role, c in messages if role.lower() == "user"]
    if not users:
        return None
    latest = users[-1]
    prev = users[-2] if len(users) >= 2 else None
    return latest, prev


def is_conversation_only_turn(
    latest_user_text: str,
    prior_user_text: Optional[str] = None,
    *,
    policy_suppress_tools: Optional[bool] = None,
) -> bool:
    """
    True when this turn should skip heavy context injection (conversation-shaped).

    When prior_user_text is set, applies short-follow-up latch like ArmaraOS.
    """
    if policy_suppress_tools is True:
        return True
    if not conversation_detection_enabled():
        return False
    if force_action_intent():
        return False

    latest = latest_user_text.strip()
    if not latest:
        return True
    if has_action_intent(latest):
        return False

    if prior_user_text:
        p = prior_user_text.strip()
        if (
            p
            and is_short_ack_or_ping_for_tool_latch(latest)
            and not is_pure_gratitude_short_ack(latest)
            and has_action_intent(p)
        ):
            return False

    return True


def is_conversation_only_messages(
    messages: Sequence[Tuple[str, str]],
    *,
    policy_suppress_tools: Optional[bool] = None,
) -> bool:
    pair = _latest_and_previous_user_text(messages)
    if pair is None:
        return True
    latest, prev = pair
    return is_conversation_only_turn(latest, prev, policy_suppress_tools=policy_suppress_tools)
