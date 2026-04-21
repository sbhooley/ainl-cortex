"""
Tests for adaptive compression profiles.
"""

import pytest
import sqlite3
from pathlib import Path
from tempfile import NamedTemporaryFile
from mcp_server.compression_profiles import (
    CompressionProfileStore,
    CompressionProfile,
    calculate_token_savings
)


@pytest.fixture
def compression_db():
    """Create temporary compression database."""
    with NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = Path(f.name)

    yield db_path

    # Cleanup
    if db_path.exists():
        db_path.unlink()


def test_init_creates_schema(compression_db):
    """Test database schema initialization."""
    store = CompressionProfileStore(compression_db)

    conn = sqlite3.connect(str(compression_db))
    cursor = conn.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='compression_profiles'
    """)

    assert cursor.fetchone() is not None
    conn.close()


def test_create_profile(compression_db):
    """Test creating a compression profile."""
    store = CompressionProfileStore(compression_db)

    profile = store.create_profile("project-123", initial_mode="balanced")

    assert profile.project_id == "project-123"
    assert profile.optimal_mode == "balanced"
    assert profile.quality_score == 1.0
    assert profile.correction_count == 0
    assert profile.success_count == 0


def test_get_profile(compression_db):
    """Test retrieving a compression profile."""
    store = CompressionProfileStore(compression_db)

    # Create profile
    created = store.create_profile("project-123")

    # Retrieve profile
    retrieved = store.get_profile("project-123")

    assert retrieved is not None
    assert retrieved.project_id == "project-123"
    assert retrieved.optimal_mode == "balanced"


def test_get_nonexistent_profile(compression_db):
    """Test retrieving nonexistent profile returns None."""
    store = CompressionProfileStore(compression_db)

    profile = store.get_profile("nonexistent")

    assert profile is None


def test_record_compression_result_success(compression_db):
    """Test recording successful compression result."""
    store = CompressionProfileStore(compression_db)

    # Record success
    store.record_compression_result(
        project_id="project-123",
        mode="balanced",
        token_savings_pct=0.3,
        user_corrected=False
    )

    # Verify profile updated
    profile = store.get_profile("project-123")
    assert profile is not None
    assert profile.success_count == 1
    assert profile.correction_count == 0
    assert profile.quality_score == 1.0  # 100% success rate


def test_record_compression_result_correction(compression_db):
    """Test recording compression with user correction."""
    store = CompressionProfileStore(compression_db)

    # Record correction
    store.record_compression_result(
        project_id="project-123",
        mode="aggressive",
        token_savings_pct=0.5,
        user_corrected=True
    )

    # Verify profile updated
    profile = store.get_profile("project-123")
    assert profile is not None
    assert profile.success_count == 0
    assert profile.correction_count == 1
    assert profile.quality_score == 0.0  # 0% success rate


def test_record_compression_ema_token_savings(compression_db):
    """Test EMA calculation for token savings."""
    store = CompressionProfileStore(compression_db)

    # Record multiple results
    store.record_compression_result("project-123", "balanced", 0.3, False)
    store.record_compression_result("project-123", "balanced", 0.5, False)

    profile = store.get_profile("project-123")

    # EMA: 0.3 * 0.3 + 0.7 * 0.0 = 0.09, then 0.3 * 0.5 + 0.7 * 0.09 = 0.213
    assert 0.2 <= profile.avg_token_savings <= 0.25


def test_auto_tune_dial_down_aggressive_to_balanced(compression_db):
    """Test auto-tune dials down from aggressive to balanced on corrections."""
    store = CompressionProfileStore(compression_db)

    # Start with aggressive mode
    store.create_profile("project-123", initial_mode="aggressive")

    # Record high correction rate (>20%)
    for _ in range(7):  # 7 successes
        store.record_compression_result("project-123", "aggressive", 0.4, False)

    for _ in range(3):  # 3 corrections (30% correction rate)
        store.record_compression_result("project-123", "aggressive", 0.4, True)

    # Should dial down to balanced
    profile = store.get_profile("project-123")
    assert profile.optimal_mode == "balanced"


def test_auto_tune_dial_down_balanced_to_off(compression_db):
    """Test auto-tune dials down from balanced to off on corrections."""
    store = CompressionProfileStore(compression_db)

    # Start with balanced mode
    store.create_profile("project-123", initial_mode="balanced")

    # Record high correction rate (>20%)
    for _ in range(7):  # 7 successes
        store.record_compression_result("project-123", "balanced", 0.3, False)

    for _ in range(3):  # 3 corrections (30% correction rate)
        store.record_compression_result("project-123", "balanced", 0.3, True)

    # Should dial down to off
    profile = store.get_profile("project-123")
    assert profile.optimal_mode == "off"


def test_auto_tune_dial_up_off_to_balanced(compression_db):
    """Test auto-tune dials up from off to balanced on high success."""
    store = CompressionProfileStore(compression_db)

    # Start with off mode
    store.create_profile("project-123", initial_mode="off")

    # Record high success rate (>90%)
    for _ in range(10):  # 10 successes, 0 corrections (100% success)
        store.record_compression_result("project-123", "off", 0.0, False)

    # Should dial up to balanced
    profile = store.get_profile("project-123")
    assert profile.optimal_mode == "balanced"


def test_auto_tune_dial_up_balanced_to_aggressive(compression_db):
    """Test auto-tune dials up from balanced to aggressive on high success."""
    store = CompressionProfileStore(compression_db)

    # Start with balanced mode
    store.create_profile("project-123", initial_mode="balanced")

    # Record high success rate (>90%)
    for _ in range(10):  # 10 successes, 0 corrections (100% success)
        store.record_compression_result("project-123", "balanced", 0.3, False)

    # Should dial up to aggressive
    profile = store.get_profile("project-123")
    assert profile.optimal_mode == "aggressive"


def test_auto_tune_requires_minimum_samples(compression_db):
    """Test auto-tune only activates after 10+ samples."""
    store = CompressionProfileStore(compression_db)

    # Start with balanced mode
    store.create_profile("project-123", initial_mode="balanced")

    # Record only 5 samples (below threshold)
    for _ in range(5):
        store.record_compression_result("project-123", "balanced", 0.3, False)

    # Should NOT change mode (not enough samples)
    profile = store.get_profile("project-123")
    assert profile.optimal_mode == "balanced"


def test_auto_tune_stays_in_sweet_spot(compression_db):
    """Test auto-tune keeps mode when in sweet spot (80-90% success)."""
    store = CompressionProfileStore(compression_db)

    # Start with balanced mode
    store.create_profile("project-123", initial_mode="balanced")

    # Record 85% success rate
    for _ in range(17):  # 17 successes
        store.record_compression_result("project-123", "balanced", 0.3, False)

    for _ in range(3):  # 3 corrections (85% success rate)
        store.record_compression_result("project-123", "balanced", 0.3, True)

    # Should stay balanced (in sweet spot)
    profile = store.get_profile("project-123")
    assert profile.optimal_mode == "balanced"


def test_get_recommended_mode_existing_profile(compression_db):
    """Test getting recommended mode for existing profile."""
    store = CompressionProfileStore(compression_db)

    store.create_profile("project-123", initial_mode="aggressive")

    mode = store.get_recommended_mode("project-123")

    assert mode == "aggressive"


def test_get_recommended_mode_new_project(compression_db):
    """Test getting recommended mode for new project returns balanced."""
    store = CompressionProfileStore(compression_db)

    mode = store.get_recommended_mode("nonexistent-project")

    assert mode == "balanced"  # Default


def test_get_stats(compression_db):
    """Test getting compression stats."""
    store = CompressionProfileStore(compression_db)

    # Record some results
    for _ in range(8):
        store.record_compression_result("project-123", "balanced", 0.3, False)

    for _ in range(2):
        store.record_compression_result("project-123", "balanced", 0.3, True)

    stats = store.get_stats("project-123")

    assert stats is not None
    assert stats['mode'] == "balanced"
    assert stats['total_compressions'] == 10
    assert stats['quality_score'] == 0.8  # 8/10
    assert stats['correction_rate'] == 20.0  # 2/10
    assert 'avg_token_savings_pct' in stats
    assert 'last_tuned' in stats


def test_get_stats_nonexistent_profile(compression_db):
    """Test getting stats for nonexistent profile returns None."""
    store = CompressionProfileStore(compression_db)

    stats = store.get_stats("nonexistent")

    assert stats is None


def test_calculate_token_savings():
    """Test token savings calculation."""
    # 50% savings
    savings = calculate_token_savings(1000, 500)
    assert savings == 0.5

    # 90% savings
    savings = calculate_token_savings(1000, 100)
    assert savings == 0.9

    # 0% savings (no compression)
    savings = calculate_token_savings(1000, 1000)
    assert savings == 0.0

    # Edge case: zero original tokens
    savings = calculate_token_savings(0, 100)
    assert savings == 0.0

    # Edge case: negative savings (expansion)
    savings = calculate_token_savings(100, 150)
    assert savings == 0.0  # Clamped to 0


def test_quality_score_calculation(compression_db):
    """Test quality score is correctly calculated as success rate."""
    store = CompressionProfileStore(compression_db)

    # 60% success rate
    for _ in range(6):
        store.record_compression_result("project-123", "balanced", 0.3, False)

    for _ in range(4):
        store.record_compression_result("project-123", "balanced", 0.3, True)

    profile = store.get_profile("project-123")

    assert profile.quality_score == 0.6  # 6/10


def test_last_tuned_only_updates_on_mode_change(compression_db):
    """Test last_tuned only updates when mode actually changes."""
    store = CompressionProfileStore(compression_db)

    store.create_profile("project-123", initial_mode="balanced")
    profile1 = store.get_profile("project-123")
    initial_tuned = profile1.last_tuned

    # Record results that don't trigger mode change
    for _ in range(5):
        store.record_compression_result("project-123", "balanced", 0.3, False)

    profile2 = store.get_profile("project-123")

    # last_tuned should not change (mode didn't change)
    assert profile2.last_tuned == initial_tuned
