"""
Adaptive compression profiles per project.
Learn optimal compression settings from user feedback.
"""

import sqlite3
from dataclasses import dataclass
from typing import Optional, Dict
from datetime import datetime
from pathlib import Path
import json


@dataclass
class CompressionProfile:
    """Per-project compression settings."""
    project_id: str
    optimal_mode: str  # off/balanced/aggressive
    avg_token_savings: float
    quality_score: float  # 0.0-1.0, based on user corrections
    correction_count: int
    success_count: int
    last_tuned: str
    created_at: str


class CompressionProfileStore:
    """Store and auto-tune compression profiles per project."""

    # Compression modes
    MODE_OFF = "off"
    MODE_BALANCED = "balanced"
    MODE_AGGRESSIVE = "aggressive"

    # Tuning thresholds
    CORRECTION_THRESHOLD = 0.2  # If >20% corrections, dial down
    SUCCESS_THRESHOLD = 0.9     # If >90% success, try dialing up

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_schema()

    def _init_schema(self):
        conn = sqlite3.connect(str(self.db_path))

        conn.execute("""
            CREATE TABLE IF NOT EXISTS compression_profiles (
                project_id TEXT PRIMARY KEY,
                optimal_mode TEXT NOT NULL,
                avg_token_savings REAL NOT NULL DEFAULT 0.0,
                quality_score REAL NOT NULL DEFAULT 1.0,
                correction_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                last_tuned TEXT NOT NULL,
                created_at TEXT NOT NULL,
                metadata TEXT
            )
        """)

        conn.commit()
        conn.close()

    def get_profile(self, project_id: str) -> Optional[CompressionProfile]:
        """Get compression profile for project."""
        conn = sqlite3.connect(str(self.db_path))

        cursor = conn.execute("""
            SELECT project_id, optimal_mode, avg_token_savings, quality_score,
                   correction_count, success_count, last_tuned, created_at
            FROM compression_profiles
            WHERE project_id = ?
        """, (project_id,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return CompressionProfile(*row)
        return None

    def create_profile(self, project_id: str, initial_mode: str = MODE_BALANCED) -> CompressionProfile:
        """Create new compression profile with defaults."""
        conn = sqlite3.connect(str(self.db_path))

        now = datetime.utcnow().isoformat()

        conn.execute("""
            INSERT INTO compression_profiles
            (project_id, optimal_mode, avg_token_savings, quality_score,
             correction_count, success_count, last_tuned, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            project_id,
            initial_mode,
            0.0,
            1.0,
            0,
            0,
            now,
            now
        ))

        conn.commit()
        conn.close()

        return CompressionProfile(
            project_id=project_id,
            optimal_mode=initial_mode,
            avg_token_savings=0.0,
            quality_score=1.0,
            correction_count=0,
            success_count=0,
            last_tuned=now,
            created_at=now
        )

    def record_compression_result(
        self,
        project_id: str,
        mode: str,
        token_savings_pct: float,
        user_corrected: bool
    ):
        """
        Record compression result and auto-tune if needed.

        Args:
            project_id: Project identifier
            mode: Compression mode used
            token_savings_pct: Token savings percentage (0.0-1.0)
            user_corrected: Whether user had to correct output
        """
        profile = self.get_profile(project_id)
        if not profile:
            profile = self.create_profile(project_id, mode)

        conn = sqlite3.connect(str(self.db_path))

        # Update stats
        new_correction_count = profile.correction_count + (1 if user_corrected else 0)
        new_success_count = profile.success_count + (0 if user_corrected else 1)
        total = new_correction_count + new_success_count

        # Calculate quality score (success rate)
        quality_score = new_success_count / total if total > 0 else 1.0

        # Update average token savings (EMA)
        alpha = 0.3
        new_avg_savings = alpha * token_savings_pct + (1 - alpha) * profile.avg_token_savings

        # Auto-tune mode if we have enough data
        new_mode = profile.optimal_mode
        should_tune = total >= 10  # Need at least 10 samples

        if should_tune:
            new_mode = self._auto_tune_mode(
                current_mode=profile.optimal_mode,
                quality_score=quality_score,
                correction_count=new_correction_count,
                success_count=new_success_count
            )

        now = datetime.utcnow().isoformat()

        conn.execute("""
            UPDATE compression_profiles
            SET optimal_mode = ?,
                avg_token_savings = ?,
                quality_score = ?,
                correction_count = ?,
                success_count = ?,
                last_tuned = ?
            WHERE project_id = ?
        """, (
            new_mode,
            new_avg_savings,
            quality_score,
            new_correction_count,
            new_success_count,
            now if new_mode != profile.optimal_mode else profile.last_tuned,
            project_id
        ))

        conn.commit()
        conn.close()

    def _auto_tune_mode(
        self,
        current_mode: str,
        quality_score: float,
        correction_count: int,
        success_count: int
    ) -> str:
        """
        Auto-tune compression mode based on quality score.

        Strategy:
        - If quality_score < 0.8 (>20% corrections): dial down
        - If quality_score > 0.9 (<10% corrections): try dialing up
        - Otherwise: keep current mode
        """
        total = correction_count + success_count
        correction_rate = correction_count / total if total > 0 else 0.0

        # Too many corrections - dial down
        if correction_rate > self.CORRECTION_THRESHOLD:
            if current_mode == self.MODE_AGGRESSIVE:
                return self.MODE_BALANCED
            elif current_mode == self.MODE_BALANCED:
                return self.MODE_OFF
            else:
                return current_mode  # Already at minimum

        # Very few corrections - try dialing up
        elif quality_score > self.SUCCESS_THRESHOLD:
            if current_mode == self.MODE_OFF:
                return self.MODE_BALANCED
            elif current_mode == self.MODE_BALANCED:
                return self.MODE_AGGRESSIVE
            else:
                return current_mode  # Already at maximum

        # In sweet spot - keep current
        else:
            return current_mode

    def get_recommended_mode(self, project_id: str) -> str:
        """Get recommended compression mode for project."""
        profile = self.get_profile(project_id)
        if profile:
            return profile.optimal_mode
        return self.MODE_BALANCED  # Default for new projects

    def get_stats(self, project_id: str) -> Optional[Dict]:
        """Get compression stats for project."""
        profile = self.get_profile(project_id)
        if not profile:
            return None

        total = profile.correction_count + profile.success_count

        return {
            'mode': profile.optimal_mode,
            'avg_token_savings_pct': profile.avg_token_savings * 100,
            'quality_score': profile.quality_score,
            'correction_rate': (profile.correction_count / total * 100) if total > 0 else 0.0,
            'total_compressions': total,
            'last_tuned': profile.last_tuned
        }


def calculate_token_savings(
    original_tokens: int,
    compressed_tokens: int
) -> float:
    """
    Calculate token savings percentage.

    Returns:
        Savings as percentage (0.0-1.0)
    """
    if original_tokens == 0:
        return 0.0

    savings = (original_tokens - compressed_tokens) / original_tokens
    return max(0.0, min(1.0, savings))


__all__ = [
    'CompressionProfileStore',
    'CompressionProfile',
    'calculate_token_savings'
]
