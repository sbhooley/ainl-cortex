"""
Tests for failure learning and resolution tracking.
"""

import pytest
import sqlite3
from pathlib import Path
from tempfile import NamedTemporaryFile
from mcp_server.failure_learning import (
    FailureLearningStore,
    FailureResolution
)


@pytest.fixture
def failure_db():
    """Create temporary failure database."""
    with NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = Path(f.name)

    yield db_path

    # Cleanup
    if db_path.exists():
        db_path.unlink()


def test_init_creates_schema(failure_db):
    """Test database schema initialization."""
    store = FailureLearningStore(failure_db)

    conn = sqlite3.connect(str(failure_db))

    # Check tables exist
    cursor = conn.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name IN ('failure_resolutions', 'failure_search')
    """)

    tables = {row[0] for row in cursor.fetchall()}
    assert 'failure_resolutions' in tables
    assert 'failure_search' in tables

    conn.close()


def test_record_failure(failure_db):
    """Test recording a failure."""
    store = FailureLearningStore(failure_db)

    failure_id = store.record_failure(
        error_type="ValidationError",
        error_message="Unknown adapter 'httP'",
        ainl_source="L1:\n  R httP.GET url",
        context={"line": 2, "col": 5}
    )

    assert failure_id is not None
    assert len(failure_id) > 0

    # Verify stored
    failure = store.get_failure(failure_id)
    assert failure is not None
    assert failure.error_type == "ValidationError"
    assert failure.error_message == "Unknown adapter 'httP'"
    assert "httP.GET" in failure.ainl_source
    assert failure.context["line"] == 2


def test_record_resolution(failure_db):
    """Test recording a resolution for a failure."""
    store = FailureLearningStore(failure_db)

    # Record failure
    failure_id = store.record_failure(
        error_type="ValidationError",
        error_message="Unknown adapter 'httP'",
        ainl_source="L1:\n  R httP.GET url",
        context={}
    )

    # Record resolution
    fixed_source = "L1:\n  R http.GET url"
    store.record_resolution(failure_id, fixed_source)

    # Verify resolution stored
    failure = store.get_failure(failure_id)
    assert failure.resolution is not None
    assert failure.resolution == fixed_source
    assert failure.resolution_diff is not None
    assert "httP" in failure.resolution_diff  # Original in diff
    assert "http" in failure.resolution_diff  # Fixed in diff
    assert failure.resolved_at is not None


def test_find_similar_failures_fts5(failure_db):
    """Test finding similar failures via FTS5 search."""
    store = FailureLearningStore(failure_db)

    # Record multiple failures
    failure1_id = store.record_failure(
        error_type="ValidationError",
        error_message="Unknown adapter 'httP' in http.GET",
        ainl_source="L1:\n  R httP.GET url",
        context={}
    )

    failure2_id = store.record_failure(
        error_type="ValidationError",
        error_message="Unknown adapter 'solna' in solana.GET_BALANCE",
        ainl_source="L1:\n  R solna.GET_BALANCE addr",
        context={}
    )

    failure3_id = store.record_failure(
        error_type="RuntimeError",
        error_message="HTTP timeout after 30s",
        ainl_source="L1:\n  R http.GET url {} 30",
        context={}
    )

    # Search for "unknown adapter"
    results = store.find_similar_failures("unknown adapter", limit=5)

    assert len(results) >= 2
    error_types = {r.error_type for r in results}
    assert "ValidationError" in error_types

    # Search for "http timeout"
    results = store.find_similar_failures("http timeout", limit=5)

    assert len(results) >= 1
    assert any("timeout" in r.error_message.lower() for r in results)


def test_find_similar_failures_returns_resolutions(failure_db):
    """Test that similar failures include resolutions if available."""
    store = FailureLearningStore(failure_db)

    # Record failure with resolution
    failure_id = store.record_failure(
        error_type="ValidationError",
        error_message="Unknown adapter 'httP'",
        ainl_source="L1:\n  R httP.GET url",
        context={}
    )

    store.record_resolution(failure_id, "L1:\n  R http.GET url")

    # Search for similar
    results = store.find_similar_failures("unknown adapter httP", limit=5)

    assert len(results) >= 1
    # Should include the resolved failure
    resolved = [r for r in results if r.resolution is not None]
    assert len(resolved) >= 1
    assert resolved[0].resolution_diff is not None


def test_increment_prevented(failure_db):
    """Test incrementing prevented count."""
    store = FailureLearningStore(failure_db)

    # Record failure with resolution
    failure_id = store.record_failure(
        error_type="ValidationError",
        error_message="Unknown adapter",
        ainl_source="L1:\n  R httP.GET url",
        context={}
    )

    store.record_resolution(failure_id, "L1:\n  R http.GET url")

    # Increment prevented count (user accepted suggestion)
    store.increment_prevented(failure_id)
    store.increment_prevented(failure_id)
    store.increment_prevented(failure_id)

    # Verify count
    failure = store.get_failure(failure_id)
    assert failure.prevented_count == 3


def test_get_failure_nonexistent(failure_db):
    """Test getting nonexistent failure returns None."""
    store = FailureLearningStore(failure_db)

    failure = store.get_failure("nonexistent-id")

    assert failure is None


def test_record_resolution_nonexistent_failure(failure_db):
    """Test recording resolution for nonexistent failure."""
    store = FailureLearningStore(failure_db)

    # Should not crash
    store.record_resolution("nonexistent-id", "fixed source")

    # Verify nothing stored
    failure = store.get_failure("nonexistent-id")
    assert failure is None


def test_failure_resolution_dataclass_fields(failure_db):
    """Test that FailureResolution has all expected fields."""
    store = FailureLearningStore(failure_db)

    failure_id = store.record_failure(
        error_type="ValidationError",
        error_message="Test error",
        ainl_source="L1:\n  out {ok: true}",
        context={"test": "data"}
    )

    failure = store.get_failure(failure_id)

    # Check all fields
    assert hasattr(failure, 'id')
    assert hasattr(failure, 'error_type')
    assert hasattr(failure, 'error_message')
    assert hasattr(failure, 'ainl_source')
    assert hasattr(failure, 'context')
    assert hasattr(failure, 'resolution')
    assert hasattr(failure, 'resolution_diff')
    assert hasattr(failure, 'prevented_count')
    assert hasattr(failure, 'created_at')
    assert hasattr(failure, 'resolved_at')

    # Check initial values
    assert failure.error_type == "ValidationError"
    assert failure.error_message == "Test error"
    assert failure.context["test"] == "data"
    assert failure.resolution is None
    assert failure.prevented_count == 0


def test_multiple_similar_failures_ranking(failure_db):
    """Test that similar failures are ranked by FTS5 relevance."""
    store = FailureLearningStore(failure_db)

    # Record failures with varying relevance
    store.record_failure(
        error_type="ValidationError",
        error_message="Unknown adapter 'httP' in HTTP call",
        ainl_source="L1:\n  R httP.GET url",
        context={}
    )

    store.record_failure(
        error_type="ValidationError",
        error_message="Timeout occurred",
        ainl_source="L1:\n  R http.GET url {} 30",
        context={}
    )

    store.record_failure(
        error_type="ValidationError",
        error_message="Unknown adapter 'httP' - check spelling",
        ainl_source="L1:\n  R httP.POST url",
        context={}
    )

    # Search for "unknown adapter httP"
    results = store.find_similar_failures("unknown adapter httP", limit=5)

    # Should return at least 2 matches
    assert len(results) >= 2

    # First result should be most relevant (contains exact phrase)
    assert "unknown adapter" in results[0].error_message.lower()


def test_fts5_search_with_no_results(failure_db):
    """Test FTS5 search returns empty list when no matches."""
    store = FailureLearningStore(failure_db)

    # Record unrelated failure
    store.record_failure(
        error_type="RuntimeError",
        error_message="Memory limit exceeded",
        ainl_source="L1:\n  out {ok: true}",
        context={}
    )

    # Search for unrelated term
    results = store.find_similar_failures("blockchain solana wallet", limit=5)

    # Should return empty or only unrelated results
    assert len(results) == 0 or "memory" in results[0].error_message.lower()


def test_context_json_serialization(failure_db):
    """Test that context dict is properly serialized/deserialized."""
    store = FailureLearningStore(failure_db)

    complex_context = {
        "line": 5,
        "col": 10,
        "file": "workflow.ainl",
        "adapters": ["http", "core"],
        "frame": {"api_key": "sk-test"}
    }

    failure_id = store.record_failure(
        error_type="ValidationError",
        error_message="Test",
        ainl_source="L1:\n  out {ok: true}",
        context=complex_context
    )

    failure = store.get_failure(failure_id)

    assert failure.context == complex_context
    assert failure.context["adapters"] == ["http", "core"]
    assert failure.context["frame"]["api_key"] == "sk-test"
