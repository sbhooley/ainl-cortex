"""
AINL Graph Store

GraphStore trait and SQLite implementation inspired by ainl-memory/src/store.rs
Provides typed graph operations with foreign key enforcement.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path
import sqlite3
import json
import logging

try:
    from .node_types import GraphNode, GraphEdge, NodeType, EdgeType
except ImportError:
    from node_types import GraphNode, GraphEdge, NodeType, EdgeType

logger = logging.getLogger(__name__)


class GraphStore(ABC):
    """
    Abstract graph store interface (inspired by ainl-memory GraphStore trait).

    This trait defines the contract for graph memory persistence without
    coupling to a specific storage backend.
    """

    @abstractmethod
    def write_node(self, node: GraphNode) -> None:
        """Write a single node (upsert by ID)"""
        pass

    @abstractmethod
    def write_edge(self, edge: GraphEdge) -> None:
        """Write a single edge"""
        pass

    @abstractmethod
    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get node by ID"""
        pass

    @abstractmethod
    def query_episodes_since(self, since: int, limit: int, project_id: Optional[str] = None) -> List[GraphNode]:
        """Query episodes after timestamp"""
        pass

    @abstractmethod
    def query_by_type(
        self, node_type: NodeType, project_id: str, limit: int, min_confidence: float = 0.0
    ) -> List[GraphNode]:
        """Query nodes by type and project"""
        pass

    @abstractmethod
    def search_fts(self, query: str, project_id: str, limit: int) -> List[GraphNode]:
        """Full-text search"""
        pass

    @abstractmethod
    def validate_graph(self, project_id: str) -> Dict[str, Any]:
        """Validate graph integrity (check for dangling edges)"""
        pass

    @abstractmethod
    def get_edges_from(self, node_id: str, edge_type: Optional[EdgeType] = None) -> List[GraphEdge]:
        """Get outgoing edges from node"""
        pass

    @abstractmethod
    def get_edges_to(self, node_id: str, edge_type: Optional[EdgeType] = None) -> List[GraphEdge]:
        """Get incoming edges to node"""
        pass

    @abstractmethod
    def get_unresolved_failures(self, project_id: str, limit: int = 100) -> List[GraphNode]:
        """Return failure nodes with no resolution yet"""
        pass

    @abstractmethod
    def update_node_data(self, node_id: str, data_patch: Dict[str, Any]) -> None:
        """Merge data_patch into a node's JSON data field"""
        pass

    @abstractmethod
    def query_goals(self, project_id: str, status: Optional[str] = None, limit: int = 50) -> List[GraphNode]:
        """Query goal nodes"""
        pass


class SQLiteGraphStore(GraphStore):
    """
    SQLite implementation of GraphStore (matches ainl-memory SqliteGraphStore).

    Features:
    - Foreign key enforcement (PRAGMA foreign_keys = ON)
    - WAL mode for concurrent reads
    - FTS5 full-text search
    - Transaction safety
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = self._open_connection()
        self._initialize_schema()

    def _open_connection(self) -> sqlite3.Connection:
        """Open SQLite connection with proper settings"""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _initialize_schema(self) -> None:
        """Initialize database schema, running migrations if needed."""
        # Detect whether the nodes table already supports the 'goal' type.
        # We inspect the CREATE TABLE SQL rather than relying on user_version,
        # because user_version=2 may have been set by a prior schema.sql run
        # without the full migration having executed.
        needs_migration = False
        try:
            row = self.conn.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'ainl_graph_nodes' AND type = 'table'"
            ).fetchone()
            if row is None or "'goal'" not in (row[0] or ''):
                needs_migration = True
        except Exception:
            needs_migration = True

        if needs_migration:
            self._migrate_to_v2()

        schema_path = Path(__file__).parent / "schema.sql"
        with open(schema_path, 'r') as f:
            schema_sql = f.read()

        self.conn.executescript(schema_sql)
        self.conn.commit()
        logger.info(f"Initialized graph store at {self.db_path}")

    def _migrate_to_v2(self) -> None:
        """
        Schema v1 → v2 migration.

        Rebuilds ainl_graph_nodes and ainl_graph_edges with updated CHECK
        constraints (adds 'goal' node type, 'A2A_THREAD' and 'GOAL_TRACKS'
        edge types).  Preserves all existing data.

        Uses direct execute() calls with FK enforcement temporarily disabled
        to safely rename tables while edges reference nodes.
        """
        logger.info("Running schema migration v1 → v2")
        try:
            # Disable FK enforcement for the duration of the rebuild
            self.conn.execute("PRAGMA foreign_keys = OFF")

            # ── Nodes table ──────────────────────────────────────────────────
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS ainl_graph_nodes_v2 (
                    id TEXT PRIMARY KEY,
                    node_type TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    agent_id TEXT DEFAULT 'claude-code',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    data JSON NOT NULL,
                    metadata JSON,
                    embedding_text TEXT,
                    CONSTRAINT valid_node_type CHECK (node_type IN (
                        'episode', 'semantic', 'procedural', 'persona',
                        'failure', 'runtime_state', 'goal'
                    )),
                    CONSTRAINT valid_confidence CHECK (
                        confidence >= 0.0 AND confidence <= 1.0
                    )
                )
            """)
            self.conn.execute(
                "INSERT OR IGNORE INTO ainl_graph_nodes_v2 SELECT * FROM ainl_graph_nodes"
            )
            self.conn.execute("DROP TABLE IF EXISTS ainl_nodes_fts")
            self.conn.execute("DROP TABLE IF EXISTS ainl_graph_nodes")
            self.conn.execute(
                "ALTER TABLE ainl_graph_nodes_v2 RENAME TO ainl_graph_nodes"
            )

            # ── Edges table ──────────────────────────────────────────────────
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS ainl_graph_edges_v2 (
                    id TEXT PRIMARY KEY,
                    edge_type TEXT NOT NULL,
                    from_node TEXT NOT NULL,
                    to_node TEXT NOT NULL,
                    project_id TEXT,
                    created_at INTEGER NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    metadata JSON,
                    FOREIGN KEY (from_node) REFERENCES ainl_graph_nodes(id) ON DELETE CASCADE,
                    FOREIGN KEY (to_node) REFERENCES ainl_graph_nodes(id) ON DELETE CASCADE,
                    CONSTRAINT valid_edge_type CHECK (edge_type IN (
                        'FOLLOWS', 'MENTIONS', 'TOUCHES', 'DEPENDS_ON', 'FIXED_BY',
                        'DERIVES_FROM', 'RELATED_TO', 'PATTERN_FOR', 'OCCURRED_IN',
                        'RESOLVES', 'EMIT_TO', 'LEARNED_FROM', 'REFERENCES',
                        'A2A_THREAD', 'GOAL_TRACKS'
                    ))
                )
            """)
            self.conn.execute(
                "INSERT OR IGNORE INTO ainl_graph_edges_v2 SELECT * FROM ainl_graph_edges"
            )
            self.conn.execute("DROP TABLE IF EXISTS ainl_graph_edges")
            self.conn.execute(
                "ALTER TABLE ainl_graph_edges_v2 RENAME TO ainl_graph_edges"
            )

            # ── FTS rebuild ──────────────────────────────────────────────────
            self.conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS ainl_nodes_fts USING fts5(
                    node_id UNINDEXED,
                    embedding_text,
                    tokenize='porter unicode61'
                )
            """)
            self.conn.execute("""
                INSERT OR IGNORE INTO ainl_nodes_fts (node_id, embedding_text)
                SELECT id, embedding_text FROM ainl_graph_nodes
                WHERE embedding_text IS NOT NULL
            """)

            self.conn.execute("PRAGMA user_version = 2")
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.commit()
            logger.info("Schema migration v1 → v2 complete")
        except Exception as e:
            self.conn.rollback()
            self.conn.execute("PRAGMA foreign_keys = ON")
            logger.warning(f"Migration v1→v2 failed (proceeding with existing schema): {e}")

    def write_node(self, node: GraphNode) -> None:
        """Write node with upsert (replace if exists)"""
        cursor = self.conn.cursor()

        try:
            cursor.execute(
                """
                INSERT OR REPLACE INTO ainl_graph_nodes
                (id, node_type, project_id, agent_id, created_at, updated_at, confidence, data, metadata, embedding_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.id,
                    node.node_type.value,
                    node.project_id,
                    node.agent_id,
                    node.created_at,
                    node.updated_at,
                    node.confidence,
                    json.dumps(node.data),
                    json.dumps(node.metadata) if node.metadata else None,
                    node.embedding_text
                )
            )

            # Update FTS index if embedding_text exists
            if node.embedding_text:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO ainl_nodes_fts (node_id, embedding_text)
                    VALUES (?, ?)
                    """,
                    (node.id, node.embedding_text)
                )

            self.conn.commit()
            logger.debug(f"Wrote node {node.id} ({node.node_type.value})")

        except sqlite3.Error as e:
            self.conn.rollback()
            logger.error(f"Failed to write node {node.id}: {e}")
            raise

    def write_edge(self, edge: GraphEdge) -> None:
        """
        Write edge with foreign key validation.

        Raises sqlite3.IntegrityError if either node doesn't exist.
        """
        cursor = self.conn.cursor()

        try:
            cursor.execute(
                """
                INSERT OR REPLACE INTO ainl_graph_edges
                (id, edge_type, from_node, to_node, project_id, created_at, confidence, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edge.id,
                    edge.edge_type.value,
                    edge.from_node,
                    edge.to_node,
                    edge.project_id,
                    edge.created_at,
                    edge.confidence,
                    json.dumps(edge.metadata) if edge.metadata else None
                )
            )

            self.conn.commit()
            logger.debug(f"Wrote edge {edge.id} ({edge.edge_type.value})")

        except sqlite3.IntegrityError as e:
            self.conn.rollback()
            logger.error(f"Foreign key violation for edge {edge.id}: {e}")
            raise

        except sqlite3.Error as e:
            self.conn.rollback()
            logger.error(f"Failed to write edge {edge.id}: {e}")
            raise

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Get node by ID"""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM ainl_graph_nodes WHERE id = ?",
            (node_id,)
        )

        row = cursor.fetchone()
        if not row:
            return None

        return self._row_to_node(row)

    def query_episodes_since(
        self, since: int, limit: int, project_id: Optional[str] = None
    ) -> List[GraphNode]:
        """Query episodes after timestamp"""
        cursor = self.conn.cursor()

        if project_id:
            cursor.execute(
                """
                SELECT * FROM ainl_graph_nodes
                WHERE node_type = 'episode'
                  AND project_id = ?
                  AND created_at >= ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (project_id, since, limit)
            )
        else:
            cursor.execute(
                """
                SELECT * FROM ainl_graph_nodes
                WHERE node_type = 'episode'
                  AND created_at >= ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (since, limit)
            )

        return [self._row_to_node(row) for row in cursor.fetchall()]

    def query_by_type(
        self,
        node_type: NodeType,
        project_id: str,
        limit: int,
        min_confidence: float = 0.0
    ) -> List[GraphNode]:
        """Query nodes by type, project, and minimum confidence"""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM ainl_graph_nodes
            WHERE node_type = ?
              AND project_id = ?
              AND confidence >= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (node_type.value, project_id, min_confidence, limit)
        )

        return [self._row_to_node(row) for row in cursor.fetchall()]

    def search_fts(self, query: str, project_id: str, limit: int) -> List[GraphNode]:
        """Full-text search using FTS5"""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT n.* FROM ainl_graph_nodes n
            JOIN ainl_nodes_fts fts ON n.id = fts.node_id
            WHERE fts.embedding_text MATCH ?
              AND n.project_id = ?
            ORDER BY fts.rank
            LIMIT ?
            """,
            (query, project_id, limit)
        )

        return [self._row_to_node(row) for row in cursor.fetchall()]

    def validate_graph(self, project_id: str) -> Dict[str, Any]:
        """
        Validate graph integrity for project.

        Returns report with:
        - dangling_edges: edges where from/to nodes don't exist
        - node_count: total nodes
        - edge_count: total edges
        """
        cursor = self.conn.cursor()

        # Count nodes
        cursor.execute(
            "SELECT COUNT(*) FROM ainl_graph_nodes WHERE project_id = ?",
            (project_id,)
        )
        node_count = cursor.fetchone()[0]

        # Count edges
        cursor.execute(
            "SELECT COUNT(*) FROM ainl_graph_edges WHERE project_id = ?",
            (project_id,)
        )
        edge_count = cursor.fetchone()[0]

        # Find dangling edges (shouldn't happen with FK enforcement, but check anyway)
        cursor.execute(
            """
            SELECT e.id, e.from_node, e.to_node, e.edge_type
            FROM ainl_graph_edges e
            WHERE e.project_id = ?
              AND (
                NOT EXISTS (SELECT 1 FROM ainl_graph_nodes WHERE id = e.from_node)
                OR NOT EXISTS (SELECT 1 FROM ainl_graph_nodes WHERE id = e.to_node)
              )
            """,
            (project_id,)
        )

        dangling_edges = [
            {
                "edge_id": row[0],
                "from_node": row[1],
                "to_node": row[2],
                "edge_type": row[3]
            }
            for row in cursor.fetchall()
        ]

        return {
            "project_id": project_id,
            "node_count": node_count,
            "edge_count": edge_count,
            "dangling_edges": dangling_edges,
            "valid": len(dangling_edges) == 0
        }

    def get_edges_from(self, node_id: str, edge_type: Optional[EdgeType] = None) -> List[GraphEdge]:
        """Get outgoing edges from node"""
        cursor = self.conn.cursor()

        if edge_type:
            cursor.execute(
                """
                SELECT * FROM ainl_graph_edges
                WHERE from_node = ? AND edge_type = ?
                ORDER BY created_at DESC
                """,
                (node_id, edge_type.value)
            )
        else:
            cursor.execute(
                """
                SELECT * FROM ainl_graph_edges
                WHERE from_node = ?
                ORDER BY created_at DESC
                """,
                (node_id,)
            )

        return [self._row_to_edge(row) for row in cursor.fetchall()]

    def get_edges_to(self, node_id: str, edge_type: Optional[EdgeType] = None) -> List[GraphEdge]:
        """Get incoming edges to node"""
        cursor = self.conn.cursor()

        if edge_type:
            cursor.execute(
                """
                SELECT * FROM ainl_graph_edges
                WHERE to_node = ? AND edge_type = ?
                ORDER BY created_at DESC
                """,
                (node_id, edge_type.value)
            )
        else:
            cursor.execute(
                """
                SELECT * FROM ainl_graph_edges
                WHERE to_node = ?
                ORDER BY created_at DESC
                """,
                (node_id,)
            )

        return [self._row_to_edge(row) for row in cursor.fetchall()]

    def _row_to_node(self, row: sqlite3.Row) -> GraphNode:
        """Convert database row to GraphNode"""
        return GraphNode(
            id=row['id'],
            node_type=NodeType(row['node_type']),
            project_id=row['project_id'],
            agent_id=row['agent_id'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
            confidence=row['confidence'],
            data=json.loads(row['data']),
            metadata=json.loads(row['metadata']) if row['metadata'] else None,
            embedding_text=row['embedding_text']
        )

    def _row_to_edge(self, row: sqlite3.Row) -> GraphEdge:
        """Convert database row to GraphEdge"""
        return GraphEdge(
            id=row['id'],
            edge_type=EdgeType(row['edge_type']),
            from_node=row['from_node'],
            to_node=row['to_node'],
            project_id=row['project_id'],
            created_at=row['created_at'],
            confidence=row['confidence'],
            metadata=json.loads(row['metadata']) if row['metadata'] else None
        )

    def get_unresolved_failures(self, project_id: str, limit: int = 100) -> List[GraphNode]:
        """Return failure nodes that have no resolution yet."""
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT * FROM ainl_graph_nodes
            WHERE node_type = 'failure'
              AND project_id = ?
              AND json_extract(data, '$.resolved_at') IS NULL
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (project_id, limit)
        )
        return [self._row_to_node(row) for row in cursor.fetchall()]

    def update_node_data(self, node_id: str, data_patch: Dict[str, Any]) -> None:
        """Merge data_patch into the existing JSON data field of a node."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT data FROM ainl_graph_nodes WHERE id = ?", (node_id,))
        row = cursor.fetchone()
        if not row:
            return
        existing = json.loads(row[0])
        existing.update(data_patch)
        now = int(__import__('time').time())
        cursor.execute(
            "UPDATE ainl_graph_nodes SET data = ?, updated_at = ? WHERE id = ?",
            (json.dumps(existing), now, node_id)
        )
        self.conn.commit()

    def query_goals(
        self,
        project_id: str,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[GraphNode]:
        """Query goal nodes, optionally filtered by status."""
        cursor = self.conn.cursor()
        if status:
            cursor.execute(
                """
                SELECT * FROM ainl_graph_nodes
                WHERE node_type = 'goal'
                  AND project_id = ?
                  AND json_extract(data, '$.status') = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (project_id, status, limit)
            )
        else:
            cursor.execute(
                """
                SELECT * FROM ainl_graph_nodes
                WHERE node_type = 'goal'
                  AND project_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (project_id, limit)
            )
        return [self._row_to_node(row) for row in cursor.fetchall()]

    def close(self) -> None:
        """Close database connection"""
        self.conn.close()
        logger.info("Closed graph store connection")
