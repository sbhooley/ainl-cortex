-- AINL Graph Memory Schema
-- Inspired by ainl-memory SQLite schema from ArmaraOS
-- Version 1.0

PRAGMA user_version = 2;
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- Core typed nodes (matches ainl-memory design)
CREATE TABLE IF NOT EXISTS ainl_graph_nodes (
    id TEXT PRIMARY KEY,                    -- UUID v4
    node_type TEXT NOT NULL,                -- episode, semantic, procedural, persona, failure, runtime_state
    project_id TEXT NOT NULL,               -- Stable project identifier
    agent_id TEXT DEFAULT 'claude-code',    -- Agent identifier
    created_at INTEGER NOT NULL,            -- Unix timestamp
    updated_at INTEGER NOT NULL,            -- Unix timestamp
    confidence REAL DEFAULT 1.0,            -- 0.0-1.0
    data JSON NOT NULL,                     -- Type-specific payload
    metadata JSON,                          -- Extensible metadata
    embedding_text TEXT,                    -- For FTS
    CONSTRAINT valid_node_type CHECK (node_type IN (
        'episode', 'semantic', 'procedural', 'persona', 'failure', 'runtime_state', 'goal'
    )),
    CONSTRAINT valid_confidence CHECK (confidence >= 0.0 AND confidence <= 1.0)
);

CREATE INDEX IF NOT EXISTS idx_nodes_type ON ainl_graph_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_nodes_project ON ainl_graph_nodes(project_id);
CREATE INDEX IF NOT EXISTS idx_nodes_created ON ainl_graph_nodes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_nodes_composite ON ainl_graph_nodes(project_id, node_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_nodes_agent_project ON ainl_graph_nodes(agent_id, project_id);
CREATE INDEX IF NOT EXISTS idx_nodes_updated ON ainl_graph_nodes(updated_at DESC);

-- Full-text search (FTS5)
CREATE VIRTUAL TABLE IF NOT EXISTS ainl_nodes_fts USING fts5(
    node_id UNINDEXED,
    embedding_text,
    tokenize='porter unicode61'
);

-- Typed edges (matches ainl-memory edge system)
CREATE TABLE IF NOT EXISTS ainl_graph_edges (
    id TEXT PRIMARY KEY,                    -- UUID v4
    edge_type TEXT NOT NULL,                -- FOLLOWS, MENTIONS, TOUCHES, DEPENDS_ON, etc.
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
);

CREATE INDEX IF NOT EXISTS idx_edges_from ON ainl_graph_edges(from_node);
CREATE INDEX IF NOT EXISTS idx_edges_to ON ainl_graph_edges(to_node);
CREATE INDEX IF NOT EXISTS idx_edges_type ON ainl_graph_edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_project ON ainl_graph_edges(project_id);
CREATE INDEX IF NOT EXISTS idx_edges_composite ON ainl_graph_edges(from_node, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_reverse ON ainl_graph_edges(to_node, edge_type);

-- Session inbox for multi-writer pattern (inspired by ainl_graph_memory_inbox.json)
CREATE TABLE IF NOT EXISTS session_inbox (
    session_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    last_active INTEGER NOT NULL,
    pending_writes JSON,                    -- Buffered node/edge writes
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_inbox_project ON session_inbox(project_id);
CREATE INDEX IF NOT EXISTS idx_inbox_active ON session_inbox(last_active DESC);

-- Autonomous task queue (AI self-scheduling and user-directed schedules)
CREATE TABLE IF NOT EXISTS autonomous_tasks (
    task_id         TEXT    PRIMARY KEY,
    project_id      TEXT    NOT NULL,
    description     TEXT    NOT NULL,
    schedule        TEXT,               -- cron expr or NULL for one-shot
    trigger_type    TEXT    NOT NULL DEFAULT 'scheduled',
    next_run_at     REAL,               -- Unix timestamp; NULL = not yet scheduled
    last_run_at     REAL,
    last_run_status TEXT,               -- 'success' | 'failed' | 'skipped'
    last_run_note   TEXT,
    status          TEXT    NOT NULL DEFAULT 'active',
    created_at      REAL    NOT NULL,
    created_by      TEXT    NOT NULL DEFAULT 'user',
    max_runs        INTEGER,            -- NULL = unlimited
    run_count       INTEGER NOT NULL DEFAULT 0,
    priority        INTEGER NOT NULL DEFAULT 5,
    allowed_actions TEXT,               -- JSON array of MCP tool names; NULL = config-list applies
    CONSTRAINT valid_task_status   CHECK (status       IN ('active','paused','cancelled','completed')),
    CONSTRAINT valid_trigger_type  CHECK (trigger_type IN ('scheduled','one_shot','goal_complete','threshold')),
    CONSTRAINT valid_priority      CHECK (priority BETWEEN 1 AND 10)
);

CREATE INDEX IF NOT EXISTS idx_tasks_project     ON autonomous_tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status      ON autonomous_tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_next_run    ON autonomous_tasks(next_run_at);
CREATE INDEX IF NOT EXISTS idx_tasks_priority    ON autonomous_tasks(project_id, status, priority DESC, next_run_at);
