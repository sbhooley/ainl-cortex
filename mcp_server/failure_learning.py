"""
Learn from failures and suggest resolutions.
"""

import sqlite3
from dataclasses import dataclass
from typing import Optional, List, Dict
from datetime import datetime, timezone
from pathlib import Path
import json


@dataclass
class FailureResolution:
    """Failure with optional resolution."""
    id: str
    error_type: str
    error_message: str
    ainl_source: str
    context: Dict
    resolution: Optional[str]
    resolution_diff: Optional[str]
    prevented_count: int
    created_at: str
    resolved_at: Optional[str]


class FailureLearningStore:
    """Store and retrieve failure resolutions."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_schema()

    def _init_schema(self):
        conn = sqlite3.connect(str(self.db_path))

        conn.execute("""
            CREATE TABLE IF NOT EXISTS failure_resolutions (
                id TEXT PRIMARY KEY,
                error_type TEXT NOT NULL,
                error_message TEXT NOT NULL,
                ainl_source TEXT NOT NULL,
                context TEXT NOT NULL,
                resolution TEXT,
                resolution_diff TEXT,
                prevented_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            )
        """)

        # FTS5 index for error message search
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS failure_search USING fts5(
                failure_id,
                error_message,
                error_type
            )
        """)

        conn.commit()
        conn.close()

    def record_failure(
        self,
        error_type: str,
        error_message: str,
        ainl_source: str,
        context: Dict
    ) -> str:
        """Record a validation failure."""
        import uuid

        failure_id = str(uuid.uuid4())

        conn = sqlite3.connect(str(self.db_path))

        conn.execute("""
            INSERT INTO failure_resolutions
            (id, error_type, error_message, ainl_source, context, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            failure_id,
            error_type,
            error_message,
            ainl_source,
            json.dumps(context),
            datetime.now(timezone.utc).isoformat()
        ))

        conn.execute("""
            INSERT INTO failure_search (failure_id, error_message, error_type)
            VALUES (?, ?, ?)
        """, (failure_id, error_message, error_type))

        conn.commit()
        conn.close()

        return failure_id

    def record_resolution(self, failure_id: str, fixed_source: str):
        """Record resolution when failure is fixed."""
        import difflib

        conn = sqlite3.connect(str(self.db_path))

        # Get original source
        cursor = conn.execute(
            "SELECT ainl_source FROM failure_resolutions WHERE id = ?",
            (failure_id,)
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return

        original = row[0]

        # Generate diff
        diff = '\n'.join(difflib.unified_diff(
            original.splitlines(),
            fixed_source.splitlines(),
            lineterm='',
            n=3
        ))

        # Update with resolution
        conn.execute("""
            UPDATE failure_resolutions
            SET resolution = ?, resolution_diff = ?, resolved_at = ?
            WHERE id = ?
        """, (fixed_source, diff, datetime.now(timezone.utc).isoformat(), failure_id))

        conn.commit()
        conn.close()

    def find_similar_failures(self, error_message: str, limit: int = 5) -> List[FailureResolution]:
        """Find similar failures via FTS5 search."""
        conn = sqlite3.connect(str(self.db_path))

        # FTS5 search
        cursor = conn.execute("""
            SELECT f.id, f.error_type, f.error_message, f.ainl_source,
                   f.context, f.resolution, f.resolution_diff, f.prevented_count,
                   f.created_at, f.resolved_at
            FROM failure_search fs
            JOIN failure_resolutions f ON fs.failure_id = f.id
            WHERE failure_search MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (error_message, limit))

        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_failure(row) for row in rows]

    def increment_prevented(self, failure_id: str):
        """Increment prevented count (user accepted suggestion)."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            UPDATE failure_resolutions
            SET prevented_count = prevented_count + 1
            WHERE id = ?
        """, (failure_id,))
        conn.commit()
        conn.close()

    def get_failure(self, failure_id: str) -> Optional[FailureResolution]:
        """Get specific failure by ID."""
        conn = sqlite3.connect(str(self.db_path))

        cursor = conn.execute("""
            SELECT * FROM failure_resolutions WHERE id = ?
        """, (failure_id,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return self._row_to_failure(row)
        return None

    def _row_to_failure(self, row) -> FailureResolution:
        return FailureResolution(
            id=row[0],
            error_type=row[1],
            error_message=row[2],
            ainl_source=row[3],
            context=json.loads(row[4]),
            resolution=row[5],
            resolution_diff=row[6],
            prevented_count=row[7],
            created_at=row[8],
            resolved_at=row[9]
        )


__all__ = ['FailureLearningStore', 'FailureResolution']
