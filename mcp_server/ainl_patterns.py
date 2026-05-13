"""AINL pattern memory integration.

Stores successful AINL workflows as reusable patterns in graph memory.
"""
import hashlib
import json
import sqlite3
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime, timezone


class AINLPatternStore:
    """
    Stores successful AINL patterns in graph memory.

    Pattern types:
    - API integration patterns
    - Data processing workflows
    - Monitoring scripts
    - Error handling patterns
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize pattern store.

        Args:
            db_path: Path to SQLite database. If None, uses in-memory DB.
        """
        self.db_path = db_path or ":memory:"
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        conn.execute("""
            CREATE TABLE IF NOT EXISTS ainl_patterns (
                id TEXT PRIMARY KEY,
                pattern_type TEXT NOT NULL,
                ainl_source TEXT NOT NULL,
                description TEXT,
                adapters_used TEXT,  -- JSON array
                fitness_score REAL DEFAULT 1.0,
                uses INTEGER DEFAULT 0,
                successes INTEGER DEFAULT 0,
                failures INTEGER DEFAULT 0,
                recurrence_count INTEGER DEFAULT 1,
                last_seen TEXT,
                tags TEXT,  -- JSON array
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT  -- JSON object
            )
        """)

        # FTS5 index for semantic search
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS ainl_patterns_fts USING fts5(
                description,
                tags,
                content=ainl_patterns,
                content_rowid=rowid
            )
        """)

        # Triggers to keep FTS in sync
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS ainl_patterns_ai AFTER INSERT ON ainl_patterns BEGIN
                INSERT INTO ainl_patterns_fts(rowid, description, tags)
                VALUES (new.rowid, new.description, new.tags);
            END
        """)

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS ainl_patterns_au AFTER UPDATE ON ainl_patterns BEGIN
                UPDATE ainl_patterns_fts
                SET description = new.description, tags = new.tags
                WHERE rowid = new.rowid;
            END
        """)

        conn.commit()
        conn.close()

    def extract_pattern(
        self,
        ainl_source: str,
        description: str,
        pattern_type: str = "general",
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Extract and store reusable pattern from AINL code.

        Args:
            ainl_source: AINL source code
            description: Human-readable description
            pattern_type: Type of pattern (api_integration, monitor, etl, etc.)
            success: Whether execution was successful
            metadata: Additional metadata

        Returns:
            Pattern ID
        """
        # Generate pattern ID from source hash
        pattern_id = self._hash_source(ainl_source)

        # Extract adapters used
        adapters = self._extract_adapters(ainl_source)

        # Extract tags from description and source
        tags = self._extract_tags(description, ainl_source)

        conn = sqlite3.connect(self.db_path)

        # Check if pattern exists
        existing = conn.execute(
            "SELECT id, uses, successes, failures, fitness_score FROM ainl_patterns WHERE id = ?",
            (pattern_id,)
        ).fetchone()

        now = datetime.now(timezone.utc).isoformat()

        if existing:
            # Update existing pattern
            uses = existing[1] + 1
            successes = existing[2] + (1 if success else 0)
            failures = existing[3] + (0 if success else 1)

            # Calculate new fitness score (EMA with alpha=0.3)
            old_fitness = existing[4]
            current_success_rate = successes / uses if uses > 0 else 1.0
            new_fitness = 0.7 * old_fitness + 0.3 * current_success_rate

            conn.execute("""
                UPDATE ainl_patterns
                SET uses = ?, successes = ?, failures = ?,
                    fitness_score = ?, recurrence_count = recurrence_count + 1,
                    last_seen = ?, updated_at = ?, metadata = ?
                WHERE id = ?
            """, (uses, successes, failures, new_fitness, now, now,
                  json.dumps(metadata or {}), pattern_id))

        else:
            # Insert new pattern
            fitness_score = 1.0 if success else 0.5

            conn.execute("""
                INSERT INTO ainl_patterns (
                    id, pattern_type, ainl_source, description,
                    adapters_used, fitness_score, uses, successes, failures,
                    recurrence_count, last_seen, tags, created_at, updated_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pattern_id, pattern_type, ainl_source, description,
                json.dumps(adapters), fitness_score, 1,
                1 if success else 0, 0 if success else 1,
                1, now,  # recurrence_count, last_seen
                json.dumps(tags), now, now, json.dumps(metadata or {})
            ))

        conn.commit()
        conn.close()

        return pattern_id

    def recall_similar(
        self,
        query: str,
        pattern_type: Optional[str] = None,
        min_fitness: float = 0.5,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find similar patterns from memory.

        Args:
            query: Search query (description or keywords)
            pattern_type: Filter by pattern type
            min_fitness: Minimum fitness score
            limit: Maximum results

        Returns:
            List of matching patterns
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Build query
        sql = """
            SELECT p.*, fts.rank
            FROM ainl_patterns p
            JOIN ainl_patterns_fts fts ON p.rowid = fts.rowid
            WHERE ainl_patterns_fts MATCH ?
            AND p.fitness_score >= ?
        """
        params = [query, min_fitness]

        if pattern_type:
            sql += " AND p.pattern_type = ?"
            params.append(pattern_type)

        sql += " ORDER BY fts.rank, p.fitness_score DESC LIMIT ?"
        params.append(limit)

        results = conn.execute(sql, params).fetchall()
        conn.close()

        return [self._row_to_dict(row) for row in results]

    def get_pattern(self, pattern_id: str) -> Optional[Dict[str, Any]]:
        """Get specific pattern by ID."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        row = conn.execute(
            "SELECT * FROM ainl_patterns WHERE id = ?",
            (pattern_id,)
        ).fetchone()

        conn.close()

        if row:
            return self._row_to_dict(row)
        return None

    def list_patterns(
        self,
        pattern_type: Optional[str] = None,
        min_fitness: float = 0.0,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """List all patterns, optionally filtered."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        sql = "SELECT * FROM ainl_patterns WHERE fitness_score >= ?"
        params = [min_fitness]

        if pattern_type:
            sql += " AND pattern_type = ?"
            params.append(pattern_type)

        sql += " ORDER BY fitness_score DESC, uses DESC LIMIT ?"
        params.append(limit)

        results = conn.execute(sql, params).fetchall()
        conn.close()

        return [self._row_to_dict(row) for row in results]

    def update_fitness(
        self,
        pattern_id: str,
        success: bool
    ) -> bool:
        """
        Update pattern fitness score based on execution result.

        Args:
            pattern_id: Pattern ID
            success: Whether execution was successful

        Returns:
            True if updated, False if pattern not found
        """
        conn = sqlite3.connect(self.db_path)

        # Get current stats
        row = conn.execute(
            "SELECT uses, successes, failures, fitness_score FROM ainl_patterns WHERE id = ?",
            (pattern_id,)
        ).fetchone()

        if not row:
            conn.close()
            return False

        uses, successes, failures, old_fitness = row
        uses += 1
        if success:
            successes += 1
        else:
            failures += 1

        # Calculate new fitness (EMA)
        current_success_rate = successes / uses if uses > 0 else 1.0
        new_fitness = 0.7 * old_fitness + 0.3 * current_success_rate

        conn.execute("""
            UPDATE ainl_patterns
            SET uses = ?, successes = ?, failures = ?,
                fitness_score = ?, updated_at = ?
            WHERE id = ?
        """, (uses, successes, failures, new_fitness,
              datetime.now(timezone.utc).isoformat(), pattern_id))

        conn.commit()
        conn.close()

        return True

    def track_recurrence(self, pattern_id: str, outcome: str = "success") -> bool:
        """
        Track pattern recurrence and update fitness score.

        Args:
            pattern_id: Pattern ID
            outcome: Execution outcome ('success', 'failure', 'partial')

        Returns:
            True if pattern was updated, False if not found
        """
        conn = sqlite3.connect(self.db_path)

        # Get current pattern
        cursor = conn.execute("""
            SELECT uses, successes, failures, fitness_score, recurrence_count
            FROM ainl_patterns WHERE id = ?
        """, (pattern_id,))

        row = cursor.fetchone()

        if not row:
            conn.close()
            return False

        uses, successes, failures, fitness, recurrence = row

        # Update counts
        uses += 1
        recurrence += 1
        if outcome == 'success':
            successes += 1
        elif outcome == 'failure':
            failures += 1

        # Calculate new fitness (EMA-style)
        success_rate = successes / uses if uses > 0 else 0.0
        alpha = 0.3  # EMA smoothing factor
        new_fitness = alpha * success_rate + (1 - alpha) * fitness

        # Update DB
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            UPDATE ainl_patterns
            SET uses = ?, successes = ?, failures = ?,
                fitness_score = ?, recurrence_count = ?, last_seen = ?, updated_at = ?
            WHERE id = ?
        """, (uses, successes, failures, new_fitness, recurrence, now, now, pattern_id))

        conn.commit()
        conn.close()

        return True

    def get_ranked_facts(
        self,
        project_id: Optional[str] = None,
        min_confidence: float = 0.5,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Get patterns ranked by confidence × recurrence × recency.

        This implements semantic fact ranking for high-signal pattern surfacing.

        Args:
            project_id: Filter by project (stored in metadata)
            min_confidence: Minimum fitness score
            limit: Maximum results

        Returns:
            List of ranked patterns with rank_score
        """
        import math

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        sql = """
            SELECT * FROM ainl_patterns
            WHERE fitness_score >= ?
        """
        params = [min_confidence]

        if project_id:
            # Filter by project_id in metadata (if stored)
            sql += " AND json_extract(metadata, '$.project_id') = ?"
            params.append(project_id)

        sql += " ORDER BY fitness_score DESC, recurrence_count DESC"

        rows = conn.execute(sql, params).fetchall()
        conn.close()

        # Calculate rank scores
        ranked = []
        now = datetime.now(timezone.utc)

        for row in rows:
            last_seen = datetime.fromisoformat(row['last_seen']) if row['last_seen'] else now
            days_old = (now - last_seen).days

            # Recency weight (exponential decay, half-life 30 days)
            recency_weight = math.exp(-days_old / 30.0)

            # Recurrence weight (logarithmic)
            recurrence_weight = 1 + math.log(1 + row['recurrence_count'])

            # Combined rank score
            rank_score = row['fitness_score'] * recurrence_weight * recency_weight

            pattern_dict = self._row_to_dict(row)
            pattern_dict['rank_score'] = rank_score
            ranked.append(pattern_dict)

        # Sort by rank and return top N
        ranked.sort(key=lambda p: p['rank_score'], reverse=True)
        return ranked[:limit]

    def _hash_source(self, source: str) -> str:
        """Generate pattern ID from source code."""
        # Normalize source (remove comments, whitespace)
        normalized = '\n'.join(
            line.strip() for line in source.split('\n')
            if line.strip() and not line.strip().startswith('#')
        )
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def _extract_adapters(self, source: str) -> List[str]:
        """Extract adapter names from AINL source."""
        import re
        # Match R adapter.verb patterns
        pattern = r'R\s+([a-z_]+)\.'
        matches = re.findall(pattern, source)
        return sorted(set(matches))

    def _extract_tags(self, description: str, source: str) -> List[str]:
        """Extract tags from description and source."""
        tags = set()

        # Common workflow keywords
        keywords = [
            'monitor', 'workflow', 'pipeline', 'api', 'endpoint',
            'cron', 'scheduled', 'automation', 'etl', 'alert',
            'blockchain', 'solana', 'llm', 'ai'
        ]

        text = (description + ' ' + source).lower()
        for kw in keywords:
            if kw in text:
                tags.add(kw)

        return sorted(tags)

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Convert SQLite row to dict."""
        d = dict(row)
        return {
            'id': d['id'],
            'pattern_type': d['pattern_type'],
            'ainl_source': d['ainl_source'],
            'description': d['description'],
            'adapters_used': json.loads(d['adapters_used']),
            'fitness_score': d['fitness_score'],
            'uses': d['uses'],
            'successes': d['successes'],
            'failures': d['failures'],
            'recurrence_count': d.get('recurrence_count', 1),
            'last_seen': d.get('last_seen'),
            'tags': json.loads(d['tags']),
            'created_at': d['created_at'],
            'updated_at': d['updated_at'],
            'metadata': json.loads(d['metadata']) if d['metadata'] else {}
        }

    def consolidate_patterns(
        self,
        min_similarity: float = 0.9,
        max_per_run: int = 50
    ) -> Dict[str, int]:
        """
        Consolidate duplicate patterns to prevent bloat.

        Finds patterns with similar source and same adapters,
        keeps the highest fitness, merges stats.

        Args:
            min_similarity: Minimum Jaccard similarity for duplicate detection
            max_per_run: Maximum patterns to consolidate per run

        Returns:
            Statistics: {'duplicates_found', 'patterns_merged', 'patterns_deleted'}
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Get all patterns grouped by adapters
        rows = conn.execute("""
            SELECT * FROM ainl_patterns
            ORDER BY adapters_used, fitness_score DESC
        """).fetchall()

        groups = {}
        for row in rows:
            adapters_key = row['adapters_used']
            if adapters_key not in groups:
                groups[adapters_key] = []
            groups[adapters_key].append(row)

        duplicates_found = 0
        patterns_merged = 0
        patterns_deleted = 0

        # Find duplicates within each adapter group
        for adapters_key, patterns in groups.items():
            if len(patterns) < 2:
                continue

            # Compare patterns pairwise
            merged = set()

            for i in range(len(patterns)):
                if patterns[i]['id'] in merged:
                    continue

                best = patterns[i]
                to_merge = []

                for j in range(i + 1, len(patterns)):
                    if patterns[j]['id'] in merged:
                        continue

                    # Calculate similarity
                    similarity = self._calculate_similarity(
                        best['ainl_source'],
                        patterns[j]['ainl_source']
                    )

                    if similarity >= min_similarity:
                        to_merge.append(patterns[j])

                if to_merge:
                    duplicates_found += len(to_merge)

                    # Merge stats into best
                    total_uses = best['uses']
                    total_successes = best['successes']
                    total_failures = best['failures']
                    total_recurrence = best.get('recurrence_count', 1)

                    for dup in to_merge:
                        total_uses += dup['uses']
                        total_successes += dup['successes']
                        total_failures += dup['failures']
                        total_recurrence += dup.get('recurrence_count', 1)

                    # Recalculate fitness
                    new_fitness = total_successes / total_uses if total_uses > 0 else best['fitness_score']

                    # Update best pattern
                    conn.execute("""
                        UPDATE ainl_patterns
                        SET uses = ?,
                            successes = ?,
                            failures = ?,
                            fitness_score = ?,
                            recurrence_count = ?,
                            updated_at = ?
                        WHERE id = ?
                    """, (
                        total_uses,
                        total_successes,
                        total_failures,
                        new_fitness,
                        total_recurrence,
                        datetime.now(timezone.utc).isoformat(),
                        best['id']
                    ))

                    patterns_merged += 1

                    # Delete duplicates
                    for dup in to_merge:
                        conn.execute("DELETE FROM ainl_patterns WHERE id = ?", (dup['id'],))
                        merged.add(dup['id'])
                        patterns_deleted += 1

                    if patterns_merged >= max_per_run:
                        break

            if patterns_merged >= max_per_run:
                break

        conn.commit()
        conn.close()

        return {
            'duplicates_found': duplicates_found,
            'patterns_merged': patterns_merged,
            'patterns_deleted': patterns_deleted
        }

    def _calculate_similarity(self, source1: str, source2: str) -> float:
        """Calculate Jaccard similarity between two AINL sources."""
        # Tokenize by lines (ignoring comments/whitespace)
        def tokenize(source):
            return set(
                line.strip()
                for line in source.split('\n')
                if line.strip() and not line.strip().startswith('#')
            )

        tokens1 = tokenize(source1)
        tokens2 = tokenize(source2)

        if not tokens1 or not tokens2:
            return 0.0

        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)

        return intersection / union if union > 0 else 0.0


def integrate_with_graph_memory(
    pattern_store: AINLPatternStore,
    graph_memory_db: str
) -> None:
    """
    Integrate AINL pattern store with existing graph memory.

    Adds AINL patterns as Procedural nodes in graph memory.
    """
    # This would integrate with the existing graph memory SQLite DB
    # For now, pattern_store is standalone
    # Future: Add ainl_patterns table to main graph memory DB
    pass


__all__ = ['AINLPatternStore', 'integrate_with_graph_memory']
