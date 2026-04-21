"""
Trajectory capture for AINL executions.
Logs every run for pattern analysis and learning.
"""

import json
import uuid
import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict


@dataclass
class TrajectoryStep:
    """Single step in AINL execution."""
    step_id: str
    timestamp: str
    adapter: str
    operation: str
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
    duration_ms: float
    success: bool
    error: Optional[str] = None


@dataclass
class ExecutionTrajectory:
    """Complete AINL execution trace."""
    trajectory_id: str
    session_id: str
    project_id: str
    ainl_source_hash: str
    ainl_source: str
    frame_vars: Dict[str, Any]
    adapters_enabled: List[str]
    executed_at: str
    duration_ms: float
    outcome: str  # success/failure/partial
    steps: List[TrajectoryStep]
    tags: List[str]
    fitness_delta: float  # change in pattern fitness


class TrajectoryStore:
    """Store and retrieve AINL execution trajectories."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_schema()

    def _init_schema(self):
        """Initialize trajectory storage schema."""
        conn = sqlite3.connect(str(self.db_path))

        conn.execute("""
            CREATE TABLE IF NOT EXISTS trajectories (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                ainl_source_hash TEXT NOT NULL,
                ainl_source TEXT NOT NULL,
                frame_vars TEXT NOT NULL,
                adapters_enabled TEXT NOT NULL,
                executed_at TEXT NOT NULL,
                duration_ms REAL NOT NULL,
                outcome TEXT NOT NULL,
                steps TEXT NOT NULL,
                tags TEXT NOT NULL,
                fitness_delta REAL NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_trajectories_session ON trajectories(session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trajectories_outcome ON trajectories(outcome)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trajectories_hash ON trajectories(ainl_source_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trajectories_project ON trajectories(project_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trajectories_executed ON trajectories(executed_at)")

        conn.commit()
        conn.close()

    def record_trajectory(self, trajectory: ExecutionTrajectory):
        """Record a complete execution trajectory."""
        conn = sqlite3.connect(str(self.db_path))

        try:
            conn.execute("""
                INSERT INTO trajectories
                (id, session_id, project_id, ainl_source_hash, ainl_source,
                 frame_vars, adapters_enabled, executed_at, duration_ms, outcome,
                 steps, tags, fitness_delta, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trajectory.trajectory_id,
                trajectory.session_id,
                trajectory.project_id,
                trajectory.ainl_source_hash,
                trajectory.ainl_source,
                json.dumps(trajectory.frame_vars),
                json.dumps(trajectory.adapters_enabled),
                trajectory.executed_at,
                trajectory.duration_ms,
                trajectory.outcome,
                '\n'.join(json.dumps(asdict(s)) for s in trajectory.steps),
                json.dumps(trajectory.tags),
                trajectory.fitness_delta,
                datetime.now().isoformat()
            ))

            conn.commit()
        finally:
            conn.close()

    def get_recent_trajectories(self, session_id: str, limit: int = 10) -> List[ExecutionTrajectory]:
        """Get recent trajectories for a session."""
        conn = sqlite3.connect(str(self.db_path))

        try:
            cursor = conn.execute("""
                SELECT * FROM trajectories
                WHERE session_id = ?
                ORDER BY executed_at DESC
                LIMIT ?
            """, (session_id, limit))

            rows = cursor.fetchall()
            return [self._row_to_trajectory(row) for row in rows]
        finally:
            conn.close()

    def get_trajectories_by_hash(self, source_hash: str) -> List[ExecutionTrajectory]:
        """Get all trajectories for a specific AINL source."""
        conn = sqlite3.connect(str(self.db_path))

        try:
            cursor = conn.execute("""
                SELECT * FROM trajectories
                WHERE ainl_source_hash = ?
                ORDER BY executed_at DESC
            """, (source_hash,))

            rows = cursor.fetchall()
            return [self._row_to_trajectory(row) for row in rows]
        finally:
            conn.close()

    def get_success_rate_by_hash(self, source_hash: str) -> float:
        """Calculate success rate for a specific AINL source."""
        conn = sqlite3.connect(str(self.db_path))

        try:
            cursor = conn.execute("""
                SELECT
                    SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) as successes,
                    COUNT(*) as total
                FROM trajectories
                WHERE ainl_source_hash = ?
            """, (source_hash,))

            row = cursor.fetchone()
            if row and row[1] > 0:
                return row[0] / row[1]
            return 0.0
        finally:
            conn.close()

    def cleanup_old_trajectories(self, days_old: int = 90):
        """Remove trajectories older than specified days."""
        conn = sqlite3.connect(str(self.db_path))

        try:
            cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            cutoff = cutoff.replace(day=cutoff.day - days_old)

            conn.execute("""
                DELETE FROM trajectories
                WHERE executed_at < ?
            """, (cutoff.isoformat(),))

            conn.commit()
        finally:
            conn.close()

    def _row_to_trajectory(self, row) -> ExecutionTrajectory:
        """Convert DB row to ExecutionTrajectory."""
        # Parse steps JSONL
        steps = []
        if row[10]:  # steps field
            for line in row[10].split('\n'):
                if line.strip():
                    try:
                        steps.append(TrajectoryStep(**json.loads(line)))
                    except:
                        pass  # Skip malformed steps

        return ExecutionTrajectory(
            trajectory_id=row[0],
            session_id=row[1],
            project_id=row[2],
            ainl_source_hash=row[3],
            ainl_source=row[4],
            frame_vars=json.loads(row[5]),
            adapters_enabled=json.loads(row[6]),
            executed_at=row[7],
            duration_ms=row[8],
            outcome=row[9],
            steps=steps,
            tags=json.loads(row[11]),
            fitness_delta=row[12]
        )


def capture_trajectory_from_run(
    ainl_source: str,
    frame: Dict[str, Any],
    adapters: Dict[str, Any],
    result: Dict[str, Any],
    session_id: str = None,
    project_id: str = None
) -> ExecutionTrajectory:
    """
    Capture trajectory from ainl_run execution.

    Args:
        ainl_source: AINL source code
        frame: Frame variables
        adapters: Adapter configuration
        result: Execution result from RuntimeEngine
        session_id: Current session ID
        project_id: Current project ID

    Returns:
        ExecutionTrajectory instance
    """
    # Generate source hash
    source_hash = hashlib.sha256(ainl_source.encode()).hexdigest()[:16]

    # Extract steps from result (if runtime provides them)
    steps = []
    if 'steps' in result:
        for step in result['steps']:
            steps.append(TrajectoryStep(
                step_id=str(uuid.uuid4()),
                timestamp=step.get('timestamp', datetime.now().isoformat()),
                adapter=step.get('adapter', 'unknown'),
                operation=step.get('operation', ''),
                inputs=step.get('inputs', {}),
                outputs=step.get('outputs', {}),
                duration_ms=step.get('duration_ms', 0.0),
                success=step.get('success', False),
                error=step.get('error')
            ))

    # Determine outcome
    if result.get('success'):
        outcome = 'success'
    elif result.get('partial_success'):
        outcome = 'partial'
    else:
        outcome = 'failure'

    # Extract tags (adapters used)
    tags = []
    if isinstance(adapters.get('enable'), list):
        tags.extend(adapters['enable'])

    # Extract adapter names from steps
    for step in steps:
        if step.adapter and step.adapter not in tags:
            tags.append(step.adapter)

    trajectory = ExecutionTrajectory(
        trajectory_id=str(uuid.uuid4()),
        session_id=session_id or 'unknown',
        project_id=project_id or 'unknown',
        ainl_source_hash=source_hash,
        ainl_source=ainl_source,
        frame_vars=frame or {},
        adapters_enabled=tags,
        executed_at=datetime.now().isoformat(),
        duration_ms=result.get('duration_ms', 0.0),
        outcome=outcome,
        steps=steps,
        tags=tags,
        fitness_delta=0.0  # Will be calculated by pattern analyzer
    )

    return trajectory


def extract_adapters_from_source(ainl_source: str) -> List[str]:
    """
    Extract adapter names from AINL source code.
    Simple heuristic: look for 'adapter.OPERATION' patterns.
    """
    import re

    # Match patterns like: http.GET, core.ADD, solana.TRANSFER_SPL
    pattern = r'\b([a-z_]+)\.[A-Z_]+'
    matches = re.findall(pattern, ainl_source)

    # Deduplicate
    return list(set(matches))
