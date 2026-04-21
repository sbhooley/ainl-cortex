"""
Tests for trajectory capture and storage.
"""

import pytest
import tempfile
import json
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_server.trajectory_capture import (
    TrajectoryStore,
    ExecutionTrajectory,
    TrajectoryStep,
    capture_trajectory_from_run,
    extract_adapters_from_source
)


class TestTrajectoryStore:
    """Test TrajectoryStore class."""

    def test_init_creates_schema(self):
        """Test that initialization creates database schema."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        try:
            store = TrajectoryStore(db_path)

            # Verify tables exist
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='trajectories'"
            )
            assert cursor.fetchone() is not None
            conn.close()

        finally:
            db_path.unlink(missing_ok=True)

    def test_record_trajectory(self):
        """Test recording a trajectory."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        try:
            store = TrajectoryStore(db_path)

            trajectory = ExecutionTrajectory(
                trajectory_id="test-123",
                session_id="session-1",
                project_id="project-1",
                ainl_source_hash="abc123",
                ainl_source="L1:\n  R core.ADD 2 3 ->sum\n  J sum",
                frame_vars={},
                adapters_enabled=["core"],
                executed_at=datetime.now().isoformat(),
                duration_ms=50.0,
                outcome="success",
                steps=[],
                tags=["core", "math"],
                fitness_delta=0.05
            )

            store.record_trajectory(trajectory)

            # Verify retrieval
            trajectories = store.get_recent_trajectories("session-1")
            assert len(trajectories) == 1
            assert trajectories[0].trajectory_id == "test-123"
            assert trajectories[0].outcome == "success"
            assert trajectories[0].project_id == "project-1"

        finally:
            db_path.unlink(missing_ok=True)

    def test_get_trajectories_by_hash(self):
        """Test retrieving trajectories for specific AINL source."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        try:
            store = TrajectoryStore(db_path)

            # Record two trajectories with same source hash
            source_hash = "abc123"

            for i in range(2):
                trajectory = ExecutionTrajectory(
                    trajectory_id=f"test-{i}",
                    session_id=f"session-{i}",
                    project_id="project-1",
                    ainl_source_hash=source_hash,
                    ainl_source="L1:\n  R core.ADD 2 3 ->sum\n  J sum",
                    frame_vars={},
                    adapters_enabled=["core"],
                    executed_at=datetime.now().isoformat(),
                    duration_ms=50.0,
                    outcome="success" if i == 0 else "failure",
                    steps=[],
                    tags=["core"],
                    fitness_delta=0.0
                )
                store.record_trajectory(trajectory)

            # Retrieve by hash
            trajectories = store.get_trajectories_by_hash(source_hash)
            assert len(trajectories) == 2
            assert trajectories[0].ainl_source_hash == source_hash
            assert trajectories[1].ainl_source_hash == source_hash

        finally:
            db_path.unlink(missing_ok=True)

    def test_get_success_rate_by_hash(self):
        """Test calculating success rate for AINL source."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        try:
            store = TrajectoryStore(db_path)

            source_hash = "abc123"

            # Record 3 successes and 1 failure
            for i in range(4):
                trajectory = ExecutionTrajectory(
                    trajectory_id=f"test-{i}",
                    session_id=f"session-{i}",
                    project_id="project-1",
                    ainl_source_hash=source_hash,
                    ainl_source="test source",
                    frame_vars={},
                    adapters_enabled=["core"],
                    executed_at=datetime.now().isoformat(),
                    duration_ms=50.0,
                    outcome="success" if i < 3 else "failure",
                    steps=[],
                    tags=[],
                    fitness_delta=0.0
                )
                store.record_trajectory(trajectory)

            # Success rate should be 0.75 (3/4)
            success_rate = store.get_success_rate_by_hash(source_hash)
            assert success_rate == 0.75

        finally:
            db_path.unlink(missing_ok=True)

    def test_trajectory_with_steps(self):
        """Test trajectory with execution steps."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = Path(f.name)

        try:
            store = TrajectoryStore(db_path)

            steps = [
                TrajectoryStep(
                    step_id="step-1",
                    timestamp=datetime.now().isoformat(),
                    adapter="core",
                    operation="ADD",
                    inputs={"a": 2, "b": 3},
                    outputs={"result": 5},
                    duration_ms=1.5,
                    success=True
                ),
                TrajectoryStep(
                    step_id="step-2",
                    timestamp=datetime.now().isoformat(),
                    adapter="http",
                    operation="GET",
                    inputs={"url": "https://api.example.com"},
                    outputs={"status": 200},
                    duration_ms=150.0,
                    success=True
                )
            ]

            trajectory = ExecutionTrajectory(
                trajectory_id="test-with-steps",
                session_id="session-1",
                project_id="project-1",
                ainl_source_hash="abc123",
                ainl_source="test",
                frame_vars={},
                adapters_enabled=["core", "http"],
                executed_at=datetime.now().isoformat(),
                duration_ms=200.0,
                outcome="success",
                steps=steps,
                tags=["core", "http"],
                fitness_delta=0.0
            )

            store.record_trajectory(trajectory)

            # Retrieve and verify steps
            retrieved = store.get_recent_trajectories("session-1")[0]
            assert len(retrieved.steps) == 2
            assert retrieved.steps[0].operation == "ADD"
            assert retrieved.steps[1].operation == "GET"
            assert retrieved.steps[0].outputs["result"] == 5

        finally:
            db_path.unlink(missing_ok=True)


class TestCaptureTrajectoryFromRun:
    """Test trajectory capture from runtime results."""

    def test_capture_successful_execution(self):
        """Test capturing successful AINL execution."""
        source = """
L1:
  R core.ADD 2 3 ->sum
  J sum
"""
        frame = {}
        adapters = {"enable": ["core"]}
        result = {
            "success": True,
            "duration_ms": 50.0,
            "steps": [
                {
                    "timestamp": datetime.now().isoformat(),
                    "adapter": "core",
                    "operation": "ADD",
                    "inputs": {"a": 2, "b": 3},
                    "outputs": {"result": 5},
                    "duration_ms": 1.5,
                    "success": True
                }
            ]
        }

        trajectory = capture_trajectory_from_run(
            ainl_source=source,
            frame=frame,
            adapters=adapters,
            result=result,
            session_id="test-session",
            project_id="test-project"
        )

        assert trajectory.outcome == "success"
        assert trajectory.duration_ms == 50.0
        assert len(trajectory.steps) == 1
        assert trajectory.session_id == "test-session"
        assert trajectory.project_id == "test-project"
        assert "core" in trajectory.adapters_enabled

    def test_capture_failed_execution(self):
        """Test capturing failed AINL execution."""
        source = "L1:\n  R unknown.VERB ->x"
        frame = {}
        adapters = {"enable": ["core"]}
        result = {
            "success": False,
            "error": "Unknown adapter: unknown",
            "duration_ms": 10.0
        }

        trajectory = capture_trajectory_from_run(
            ainl_source=source,
            frame=frame,
            adapters=adapters,
            result=result,
            session_id="test-session",
            project_id="test-project"
        )

        assert trajectory.outcome == "failure"
        assert trajectory.duration_ms == 10.0

    def test_capture_with_defaults(self):
        """Test capture with missing session/project IDs."""
        source = "L1:\n  R core.ADD 1 1 ->x"
        result = {"success": True, "duration_ms": 5.0}

        trajectory = capture_trajectory_from_run(
            ainl_source=source,
            frame={},
            adapters={},
            result=result
        )

        assert trajectory.session_id == "unknown"
        assert trajectory.project_id == "unknown"


class TestExtractAdaptersFromSource:
    """Test adapter extraction from AINL source."""

    def test_extract_single_adapter(self):
        """Test extracting single adapter from source."""
        source = """
L1:
  R http.GET "https://api.example.com" {} 30 ->response
  J response
"""
        adapters = extract_adapters_from_source(source)
        assert "http" in adapters

    def test_extract_multiple_adapters(self):
        """Test extracting multiple adapters from source."""
        source = """
L1:
  R http.GET "https://api.example.com" {} 30 ->data
  R core.GET data "value" ->val
  R sqlite.QUERY "SELECT * FROM users" ->rows
  J rows
"""
        adapters = extract_adapters_from_source(source)
        assert "http" in adapters
        assert "core" in adapters
        assert "sqlite" in adapters

    def test_extract_deduplicates(self):
        """Test that adapter extraction deduplicates."""
        source = """
L1:
  R http.GET "url1" {} 30 ->r1
  R http.POST "url2" {} 30 ->r2
  R http.GET "url3" {} 30 ->r3
"""
        adapters = extract_adapters_from_source(source)
        assert adapters == ["http"]  # Only one entry


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
