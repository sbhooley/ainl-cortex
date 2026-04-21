"""
Closed loop validation system for AINL improvements.
Propose improvements → validate strictly → track success rate.
"""

import sqlite3
import json
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from datetime import datetime
from pathlib import Path
import hashlib


@dataclass
class ImprovementProposal:
    """AINL improvement proposal with validation."""
    id: str
    original_source: str
    original_hash: str
    proposed_source: str
    proposed_hash: str
    improvement_type: str  # optimize, refactor, fix, enhance
    rationale: str
    validation_passed: bool
    validation_details: Optional[Dict]
    accepted: Optional[bool]
    created_at: str
    accepted_at: Optional[str]


class ImprovementProposalStore:
    """Store and track improvement proposals."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_schema()

    def _init_schema(self):
        conn = sqlite3.connect(str(self.db_path))

        conn.execute("""
            CREATE TABLE IF NOT EXISTS improvement_proposals (
                id TEXT PRIMARY KEY,
                original_source TEXT NOT NULL,
                original_hash TEXT NOT NULL,
                proposed_source TEXT NOT NULL,
                proposed_hash TEXT NOT NULL,
                improvement_type TEXT NOT NULL,
                rationale TEXT NOT NULL,
                validation_passed INTEGER NOT NULL,
                validation_details TEXT,
                accepted INTEGER,
                created_at TEXT NOT NULL,
                accepted_at TEXT
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_proposals_original
            ON improvement_proposals(original_hash)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_proposals_type
            ON improvement_proposals(improvement_type)
        """)

        conn.commit()
        conn.close()

    def _hash_source(self, source: str) -> str:
        """Generate hash of AINL source."""
        normalized = '\n'.join(
            line.strip() for line in source.split('\n')
            if line.strip() and not line.strip().startswith('#')
        )
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def propose_improvement(
        self,
        original_source: str,
        proposed_source: str,
        improvement_type: str,
        rationale: str,
        validation_result: Dict[str, Any]
    ) -> str:
        """Record an improvement proposal."""
        import uuid

        proposal_id = str(uuid.uuid4())
        original_hash = self._hash_source(original_source)
        proposed_hash = self._hash_source(proposed_source)

        validation_passed = validation_result.get('valid', False)

        conn = sqlite3.connect(str(self.db_path))

        conn.execute("""
            INSERT INTO improvement_proposals
            (id, original_source, original_hash, proposed_source, proposed_hash,
             improvement_type, rationale, validation_passed, validation_details,
             accepted, created_at, accepted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            proposal_id,
            original_source,
            original_hash,
            proposed_source,
            proposed_hash,
            improvement_type,
            rationale,
            1 if validation_passed else 0,
            json.dumps(validation_result),
            None,
            datetime.now().isoformat(),
            None
        ))

        conn.commit()
        conn.close()

        return proposal_id

    def mark_accepted(self, proposal_id: str, accepted: bool):
        """Mark proposal as accepted/rejected by user."""
        conn = sqlite3.connect(str(self.db_path))

        now = datetime.now().isoformat()

        conn.execute("""
            UPDATE improvement_proposals
            SET accepted = ?, accepted_at = ?
            WHERE id = ?
        """, (1 if accepted else 0, now, proposal_id))

        conn.commit()
        conn.close()

    def get_success_rate(
        self,
        improvement_type: Optional[str] = None,
        min_proposals: int = 5
    ) -> Optional[float]:
        """Get acceptance rate for improvement proposals."""
        conn = sqlite3.connect(str(self.db_path))

        sql = """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN accepted = 1 THEN 1 ELSE 0 END) as accepted
            FROM improvement_proposals
            WHERE accepted IS NOT NULL
              AND validation_passed = 1
        """

        params = []
        if improvement_type:
            sql += " AND improvement_type = ?"
            params.append(improvement_type)

        cursor = conn.execute(sql, params)
        row = cursor.fetchone()
        conn.close()

        if not row or row[0] < min_proposals:
            return None

        total, accepted = row
        return accepted / total if total > 0 else 0.0

    def get_confidence_adjustment(
        self,
        improvement_type: str
    ) -> float:
        """Get confidence adjustment based on historical success rate."""
        success_rate = self.get_success_rate(improvement_type)

        if success_rate is None:
            return 0.7  # Default moderate confidence

        # Map success rate to confidence
        # 80%+ success → 0.9 confidence
        # 50% success → 0.6 confidence
        # 20% success → 0.3 confidence
        return max(0.3, min(0.95, success_rate * 1.1))

    def get_recent_proposals(
        self,
        original_hash: Optional[str] = None,
        limit: int = 10
    ) -> List[ImprovementProposal]:
        """Get recent proposals, optionally filtered by original source."""
        conn = sqlite3.connect(str(self.db_path))

        sql = "SELECT * FROM improvement_proposals"
        params = []

        if original_hash:
            sql += " WHERE original_hash = ?"
            params.append(original_hash)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()

        proposals = []
        for row in rows:
            validation_details = json.loads(row[8]) if row[8] else None

            proposals.append(ImprovementProposal(
                id=row[0],
                original_source=row[1],
                original_hash=row[2],
                proposed_source=row[3],
                proposed_hash=row[4],
                improvement_type=row[5],
                rationale=row[6],
                validation_passed=bool(row[7]),
                validation_details=validation_details,
                accepted=bool(row[9]) if row[9] is not None else None,
                created_at=row[10],
                accepted_at=row[11]
            ))

        return proposals


def generate_diff(original: str, proposed: str) -> str:
    """Generate unified diff between original and proposed source."""
    import difflib

    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        proposed.splitlines(keepends=True),
        fromfile='original.ainl',
        tofile='proposed.ainl',
        lineterm=''
    )

    return ''.join(diff)


__all__ = [
    'ImprovementProposalStore',
    'ImprovementProposal',
    'generate_diff'
]
