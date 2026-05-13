"""
Tests for pattern recurrence tracking and semantic ranking.
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.ainl_patterns import AINLPatternStore


class TestPatternRecurrence:
    """Test pattern recurrence tracking."""

    def test_track_recurrence_success(self):
        """Test tracking successful pattern execution."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            store = AINLPatternStore(db_path)

            # Create initial pattern
            source = "L1:\n  R core.ADD 2 3 ->sum\n  J sum"
            pattern_id = store.extract_pattern(
                ainl_source=source,
                description="Add two numbers",
                pattern_type="math",
                success=True
            )

            # Get initial state
            pattern = store.get_pattern(pattern_id)
            initial_recurrence = pattern['recurrence_count']
            initial_fitness = pattern['fitness_score']

            # Track recurrence (success)
            result = store.track_recurrence(pattern_id, outcome="success")
            assert result is True

            # Verify updates
            pattern = store.get_pattern(pattern_id)
            assert pattern['recurrence_count'] == initial_recurrence + 1
            assert pattern['uses'] == 2
            assert pattern['successes'] == 2
            assert pattern['fitness_score'] >= initial_fitness  # Should improve

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_track_recurrence_failure(self):
        """Test tracking failed pattern execution."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            store = AINLPatternStore(db_path)

            # Create initial pattern
            source = "L1:\n  R http.GET url {} 30 ->r\n  J r"
            pattern_id = store.extract_pattern(
                ainl_source=source,
                description="HTTP GET request",
                pattern_type="api",
                success=True
            )

            # Track failure
            result = store.track_recurrence(pattern_id, outcome="failure")
            assert result is True

            # Verify updates
            pattern = store.get_pattern(pattern_id)
            assert pattern['uses'] == 2
            assert pattern['successes'] == 1
            assert pattern['failures'] == 1
            assert pattern['fitness_score'] < 1.0  # Should decrease

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_track_recurrence_ema_smoothing(self):
        """Test that fitness uses EMA smoothing."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            store = AINLPatternStore(db_path)

            # Create pattern with an initial failure so EMA convergence is observable
            # (success=True would start at fitness=1.0 leaving no room to increase)
            source = "L1:\n  R core.ADD x y ->sum"
            pattern_id = store.extract_pattern(
                ainl_source=source,
                description="Test",
                success=False
            )

            # Track multiple successes
            fitness_scores = [store.get_pattern(pattern_id)['fitness_score']]

            for _ in range(5):
                store.track_recurrence(pattern_id, outcome="success")
                fitness_scores.append(store.get_pattern(pattern_id)['fitness_score'])

            # Fitness should converge to 1.0 but use EMA (not jump immediately)
            assert fitness_scores[-1] > fitness_scores[0]
            assert fitness_scores[-1] <= 1.0

            # Check EMA property: each update moves toward target
            for i in range(1, len(fitness_scores)):
                # New value should be between old value and target (1.0)
                assert fitness_scores[i-1] <= fitness_scores[i] <= 1.0

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_track_recurrence_nonexistent_pattern(self):
        """Test tracking recurrence for non-existent pattern."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            store = AINLPatternStore(db_path)

            # Try to track non-existent pattern
            result = store.track_recurrence("nonexistent-id", outcome="success")
            assert result is False

        finally:
            Path(db_path).unlink(missing_ok=True)


class TestSemanticRanking:
    """Test semantic fact ranking."""

    def test_get_ranked_facts_basic(self):
        """Test basic ranked fact retrieval."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            store = AINLPatternStore(db_path)

            # Create patterns with different fitness scores
            patterns = [
                ("L1:\n  R core.ADD 1 2 ->x", "Add numbers", 0.9),
                ("L1:\n  R http.GET url {} 30 ->r", "HTTP request", 0.7),
                ("L1:\n  R core.MUL 3 4 ->x", "Multiply", 0.5),
            ]

            for source, desc, _ in patterns:
                store.extract_pattern(source, desc, success=True)

            # Get ranked facts
            ranked = store.get_ranked_facts(min_confidence=0.0, limit=3)

            assert len(ranked) == 3
            # Should be ordered by rank_score (fitness × recurrence × recency)
            for i in range(len(ranked) - 1):
                assert ranked[i]['rank_score'] >= ranked[i+1]['rank_score']

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_get_ranked_facts_recency_weight(self):
        """Test that recency affects ranking."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            store = AINLPatternStore(db_path)

            # Create two patterns with same fitness
            p1_id = store.extract_pattern(
                "L1:\n  R core.ADD 1 2 ->x",
                "Recent pattern",
                success=True
            )

            p2_id = store.extract_pattern(
                "L1:\n  R core.SUB 5 3 ->x",
                "Old pattern",
                success=True
            )

            # Make p2 appear old by directly updating last_seen
            import sqlite3
            conn = sqlite3.connect(db_path)
            old_date = (datetime.utcnow() - timedelta(days=60)).isoformat()
            conn.execute(
                "UPDATE ainl_patterns SET last_seen = ? WHERE id = ?",
                (old_date, p2_id)
            )
            conn.commit()
            conn.close()

            # Get ranked facts
            ranked = store.get_ranked_facts(limit=2)

            # Recent pattern should rank higher
            assert ranked[0]['rank_score'] > ranked[1]['rank_score']
            assert ranked[0]['id'] == p1_id

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_get_ranked_facts_recurrence_weight(self):
        """Test that recurrence count affects ranking."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            store = AINLPatternStore(db_path)

            # Create two patterns
            p1_id = store.extract_pattern(
                "L1:\n  R core.ADD 1 2 ->x",
                "Frequent pattern",
                success=True
            )

            p2_id = store.extract_pattern(
                "L1:\n  R core.SUB 5 3 ->x",
                "Rare pattern",
                success=True
            )

            # Track p1 many times
            for _ in range(10):
                store.track_recurrence(p1_id, outcome="success")

            # Track p2 once
            store.track_recurrence(p2_id, outcome="success")

            # Get ranked facts
            ranked = store.get_ranked_facts(limit=2)

            # Frequent pattern should rank higher (due to recurrence)
            assert ranked[0]['id'] == p1_id
            assert ranked[0]['recurrence_count'] > ranked[1]['recurrence_count']

        finally:
            Path(db_path).unlink(missing_ok=True)

    def test_get_ranked_facts_min_confidence_filter(self):
        """Test minimum confidence filtering."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            store = AINLPatternStore(db_path)

            # Create patterns with different fitness
            store.extract_pattern("L1:\n  R core.ADD 1 2 ->x", "High", success=True)
            p_low = store.extract_pattern("L1:\n  R core.SUB 1 2 ->x", "Low", success=False)

            # Track low pattern to reduce fitness
            for _ in range(3):
                store.track_recurrence(p_low, outcome="failure")

            # Get with min_confidence filter
            ranked = store.get_ranked_facts(min_confidence=0.6, limit=10)

            # Low fitness pattern should be filtered out
            assert all(p['fitness_score'] >= 0.6 for p in ranked)

        finally:
            Path(db_path).unlink(missing_ok=True)


class TestPatternLifecycle:
    """Test complete pattern lifecycle with recurrence tracking."""

    def test_pattern_creation_and_evolution(self):
        """Test pattern creation and evolution through recurrence."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            store = AINLPatternStore(db_path)

            source = """
L1:
  R http.GET "https://api.example.com/data" {} 30 ->response
  R core.GET response "items" ->items
  R core.LEN items ->count
  J count
"""

            # Initial extraction (success)
            pattern_id = store.extract_pattern(
                ainl_source=source,
                description="Fetch and count API items",
                pattern_type="api_integration",
                success=True
            )

            pattern = store.get_pattern(pattern_id)
            assert pattern['uses'] == 1
            assert pattern['successes'] == 1
            assert pattern['recurrence_count'] == 1
            assert pattern['fitness_score'] == 1.0

            # Execute again (success)
            store.track_recurrence(pattern_id, outcome="success")
            pattern = store.get_pattern(pattern_id)
            assert pattern['uses'] == 2
            assert pattern['successes'] == 2
            assert pattern['recurrence_count'] == 2
            assert pattern['fitness_score'] == 1.0

            # Execute with failure
            store.track_recurrence(pattern_id, outcome="failure")
            pattern = store.get_pattern(pattern_id)
            assert pattern['uses'] == 3
            assert pattern['successes'] == 2
            assert pattern['failures'] == 1
            assert pattern['recurrence_count'] == 3
            assert 0.6 <= pattern['fitness_score'] < 1.0  # Should decrease

            # More successes should recover fitness
            for _ in range(5):
                store.track_recurrence(pattern_id, outcome="success")

            pattern = store.get_pattern(pattern_id)
            assert pattern['uses'] == 8
            assert pattern['successes'] == 7
            assert pattern['failures'] == 1
            assert pattern['recurrence_count'] == 8
            assert pattern['fitness_score'] > 0.8  # Should recover

        finally:
            Path(db_path).unlink(missing_ok=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
