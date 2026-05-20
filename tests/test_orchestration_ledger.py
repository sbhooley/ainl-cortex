"""AINL promotion counterfactuals."""

from mcp_server.orchestration_ledger import (
    BASELINE_TAG,
    format_promotion_nudge,
    promotion_suggestion,
    trajectory_fingerprint,
)


def test_promotion_below_threshold():
    s = promotion_suggestion(3)
    assert s["suggest"] is False


def test_promotion_at_threshold():
    s = promotion_suggestion(5)
    assert s["suggest"] is True
    assert s["baseline_tag"] == BASELINE_TAG
    assert s["est_tokens_saved_if_ainl"] == 5 * 2500


def test_fingerprint_stable():
    assert trajectory_fingerprint(["read", "edit"]) == trajectory_fingerprint(["read", "edit"])


def test_format_nudge_nonempty():
    n = format_promotion_nudge(promotion_suggestion(6))
    assert "baseline_C" in n
