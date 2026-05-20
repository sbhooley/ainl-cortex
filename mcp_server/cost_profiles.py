"""Map cost_profile presets onto plugin config overrides."""

from __future__ import annotations

from typing import Any, Dict

COST_PROFILE_PRESETS: Dict[str, Dict[str, Any]] = {
    "balanced": {},
    "subscription_safe": {
        "memory": {
            "recall_detail_level": "minimal",
            "recall_max_items_per_type": {
                "episodes": 2,
                "facts": 3,
                "patterns": 1,
                "failures": 2,
                "persona": 2,
            },
            "recall_min_prompt_chars": 80,
        },
        "compression": {
            "mode": "balanced",
            "compress_memory_context": True,
            "compress_user_prompt": True,
            "output": {"enabled": False},
        },
        "failure_advisor": {"max_warnings": 2},
        "conversation": {"enabled": True, "suppress_mcp_hint": True},
    },
    "max_learning": {
        "memory": {
            "recall_detail_level": "verbose",
            "recall_max_items_per_type": {
                "episodes": 5,
                "facts": 8,
                "patterns": 4,
                "failures": 5,
                "persona": 5,
            },
        },
        "compression": {
            "mode": "off",
            "enabled": False,
        },
    },
}


def apply_cost_profile(config: Dict[str, Any]) -> Dict[str, Any]:
    """Deep-merge cost_profile preset into config (preset keys only if not set)."""
    raw = config.get("cost_profile", "balanced")
    profile = str(raw or "balanced").strip().lower()
    preset = COST_PROFILE_PRESETS.get(profile)
    if not preset:
        return config

    from .config_loader import deep_merge

    return deep_merge(config, preset)
