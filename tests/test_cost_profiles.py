"""Cost profile preset merges."""

from mcp_server.cost_profiles import apply_cost_profile


def test_subscription_safe_sets_minimal_recall():
    cfg = apply_cost_profile({"cost_profile": "subscription_safe", "memory": {}})
    assert cfg["memory"]["recall_detail_level"] == "minimal"
    assert cfg["failure_advisor"]["max_warnings"] == 2


def test_balanced_leaves_defaults():
    cfg = apply_cost_profile({"cost_profile": "balanced", "memory": {"recall_detail_level": "standard"}})
    assert cfg["memory"]["recall_detail_level"] == "standard"


def test_unknown_profile_passthrough():
    cfg = apply_cost_profile({"cost_profile": "custom_xyz", "memory": {"recall_detail_level": "verbose"}})
    assert cfg["memory"]["recall_detail_level"] == "verbose"
