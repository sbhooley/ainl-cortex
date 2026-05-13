//! PyO3 bindings for SqliteGraphStore.
//!
//! All methods return Python dicts/lists via serde_json round-trip.
//!
//! SqliteGraphStore is !Sync due to RefCell in rusqlite::Connection.
//! It IS Send, so Mutex<Store> satisfies PyO3's required Send + Sync.

use crate::convert::{from_py, to_py};
use ainl_memory::{
    anchored_summary::{anchored_summary_id, ANCHORED_SUMMARY_TAG},
    node::{AinlNodeType, MemoryCategory, SemanticNode},
    query::walk_from,
    store::{GraphStore, SqliteGraphStore},
    AinlMemoryNode,
};
use ainl_memory::trajectory_table::TrajectoryDetailRecord;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::path::Path;
use std::sync::Mutex;
use uuid::Uuid;

#[pyclass]
pub struct AinlNativeStore {
    inner: Mutex<SqliteGraphStore>,
}

impl AinlNativeStore {
    /// Lock the inner store, converting a poisoned-mutex error into a
    /// catchable Python `RuntimeError` instead of letting the panic from
    /// `.unwrap()` abort the whole Python interpreter.
    ///
    /// A `Mutex` is poisoned only when a thread holding the guard panics;
    /// in that case the data is potentially inconsistent and we surface a
    /// clear error to the Python side rather than risking a hard crash of
    /// the MCP server hosting this store.
    fn lock_inner(&self) -> PyResult<std::sync::MutexGuard<'_, SqliteGraphStore>> {
        self.inner.lock().map_err(|poison| {
            pyo3::exceptions::PyRuntimeError::new_err(format!(
                "ainl_native store mutex was poisoned by an earlier panic: {}",
                poison
            ))
        })
    }
}

#[pymethods]
impl AinlNativeStore {
    /// Open or create the graph memory database at the given path.
    #[staticmethod]
    fn open(db_path: &str) -> PyResult<Self> {
        let store = SqliteGraphStore::open(Path::new(db_path))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        Ok(Self {
            inner: Mutex::new(store),
        })
    }

    /// Write a node dict into the graph.
    fn write_node(&self, node_dict: &Bound<'_, pyo3::PyAny>) -> PyResult<()> {
        let node: AinlMemoryNode = from_py(node_dict)?;
        self.lock_inner()?
            .write_node(&node)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))
    }

    /// Read a node by UUID string. Returns None if not found.
    fn read_node(&self, py: Python<'_>, node_id: &str) -> PyResult<Option<PyObject>> {
        let id = Uuid::parse_str(node_id)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        match self
            .lock_inner()?
            .read_node(id)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?
        {
            Some(node) => Ok(Some(to_py(py, &node)?)),
            None => Ok(None),
        }
    }

    /// Query episode nodes since a Unix timestamp. Returns list of dicts.
    fn query_episodes_since(
        &self,
        py: Python<'_>,
        since_timestamp: i64,
        limit: usize,
    ) -> PyResult<PyObject> {
        let nodes = self.lock_inner()?
            .query_episodes_since(since_timestamp, limit)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        to_py(py, &nodes)
    }

    /// Find all nodes of a given type_name. Returns list of dicts.
    fn find_by_type(&self, py: Python<'_>, type_name: &str) -> PyResult<PyObject> {
        let nodes = self.lock_inner()?
            .find_by_type(type_name)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        to_py(py, &nodes)
    }

    /// Walk direct edges from a node with given label. Returns list of neighbor dicts.
    fn walk_edges(
        &self,
        py: Python<'_>,
        from_id: &str,
        label: &str,
    ) -> PyResult<PyObject> {
        let id = Uuid::parse_str(from_id)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        let nodes = self.lock_inner()?
            .walk_edges(id, label)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        to_py(py, &nodes)
    }

    /// Walk edges TO a node (reverse traversal). Returns list of source node dicts.
    fn walk_edges_to(
        &self,
        py: Python<'_>,
        to_id: &str,
        label: &str,
    ) -> PyResult<PyObject> {
        let id = Uuid::parse_str(to_id)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        let nodes = self.lock_inner()?
            .walk_edges_to(id, label)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        to_py(py, &nodes)
    }

    /// Insert a directed edge between two node UUIDs.
    fn insert_edge(&self, from_id: &str, to_id: &str, label: &str) -> PyResult<()> {
        let from = Uuid::parse_str(from_id)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        let to = Uuid::parse_str(to_id)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        self.lock_inner()?
            .insert_graph_edge(from, to, label)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))
    }

    /// Walk graph from start_id following edge_label up to max_depth hops.
    fn walk_from(
        &self,
        py: Python<'_>,
        start_id: &str,
        edge_label: &str,
        max_depth: usize,
    ) -> PyResult<PyObject> {
        let id = Uuid::parse_str(start_id)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        let guard = self.lock_inner()?;
        let nodes = walk_from(&*guard, id, edge_label, max_depth)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        to_py(py, &nodes)
    }

    /// FTS search over failure nodes for one agent. Returns list of dicts.
    fn search_failures(
        &self,
        py: Python<'_>,
        agent_id: &str,
        query: &str,
        limit: usize,
    ) -> PyResult<PyObject> {
        let nodes = self.lock_inner()?
            .search_failures_fts_for_agent(agent_id, query, limit)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        to_py(py, &nodes)
    }

    /// FTS search across all node types for one agent. Returns list of dicts.
    #[pyo3(signature = (agent_id, query, limit, project_id=None))]
    fn search_all(
        &self,
        py: Python<'_>,
        agent_id: &str,
        query: &str,
        limit: usize,
        project_id: Option<&str>,
    ) -> PyResult<PyObject> {
        let nodes = self.lock_inner()?
            .search_all_nodes_fts_for_agent(agent_id, query, project_id, limit)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        to_py(py, &nodes)
    }

    /// Validate graph integrity for one agent. Returns summary dict.
    fn validate_graph(&self, py: Python<'_>, agent_id: &str) -> PyResult<PyObject> {
        let report = self
            .lock_inner()?
            .validate_graph(agent_id)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        let d = PyDict::new(py);
        d.set_item("agent_id", &report.agent_id)?;
        d.set_item("node_count", report.node_count)?;
        d.set_item("edge_count", report.edge_count)?;
        d.set_item("is_valid", report.is_valid)?;
        d.set_item("orphan_node_count", report.orphan_nodes.len())?;
        d.set_item("cross_agent_boundary_edges", report.cross_agent_boundary_edges)?;
        d.set_item("dangling_edge_count", report.dangling_edges.len())?;
        Ok(d.into())
    }

    /// Insert a trajectory detail row.
    fn insert_trajectory(&self, trajectory_dict: &Bound<'_, pyo3::PyAny>) -> PyResult<()> {
        let row: TrajectoryDetailRecord = from_py(trajectory_dict)?;
        self.lock_inner()?
            .insert_trajectory_detail(&row)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))
    }

    /// List trajectory details for one agent, optionally filtered by since_timestamp.
    #[pyo3(signature = (agent_id, limit, since_timestamp=None))]
    fn list_trajectories(
        &self,
        py: Python<'_>,
        agent_id: &str,
        limit: usize,
        since_timestamp: Option<i64>,
    ) -> PyResult<PyObject> {
        let rows = self
            .lock_inner()?
            .list_trajectories_for_agent(agent_id, limit, since_timestamp)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        to_py(py, &rows)
    }

    /// Record an episode node and return its graph node UUID string (the FK-referenced ID).
    /// trace_event_json: optional JSON string for the orchestration trace
    #[pyo3(signature = (tools, sub_agent_id=None, trace_event_json=None))]
    fn record_episode(
        &self,
        tools: Vec<String>,
        sub_agent_id: Option<String>,
        trace_event_json: Option<&str>,
    ) -> PyResult<String> {
        let trace: Option<serde_json::Value> = match trace_event_json {
            Some(s) => Some(
                serde_json::from_str(s)
                    .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?,
            ),
            None => None,
        };
        let turn_id = Uuid::new_v4();
        let timestamp = chrono::Utc::now().timestamp();
        let node = AinlMemoryNode::new_episode(turn_id, timestamp, tools, sub_agent_id, trace);
        let node_id = node.id; // This is the graph node ID referenced by FK constraints
        self.lock_inner()?
            .write_node(&node)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        Ok(node_id.to_string())
    }

    /// Export the full agent graph as a snapshot dict.
    fn export_graph(&self, py: Python<'_>, agent_id: &str) -> PyResult<PyObject> {
        let snapshot = self
            .lock_inner()?
            .export_graph(agent_id)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        to_py(py, &snapshot)
    }

    // ── High-level plugin node writers ──────────────────────────────────────

    /// Write a Semantic node. Returns the node UUID string.
    /// plugin_data: arbitrary Python dict stored in plugin_data field (for Python-specific extras).
    #[pyo3(signature = (agent_id, fact, confidence, source_turn_id=None, topic_cluster=None, tags=None, plugin_data=None))]
    fn write_semantic(
        &self,
        agent_id: &str,
        fact: &str,
        confidence: f32,
        source_turn_id: Option<&str>,
        topic_cluster: Option<&str>,
        tags: Option<Vec<String>>,
        plugin_data: Option<&Bound<'_, pyo3::PyAny>>,
    ) -> PyResult<String> {
        use ainl_memory::node::{AinlNodeType, SemanticNode};
        let src = source_turn_id
            .and_then(|s| Uuid::parse_str(s).ok())
            .unwrap_or_else(Uuid::new_v4);
        let semantic = SemanticNode {
            fact: fact.to_string(),
            confidence: confidence.clamp(0.0, 1.0),
            source_turn_id: src,
            topic_cluster: topic_cluster.map(str::to_string),
            source_episode_id: String::new(),
            contradiction_ids: Vec::new(),
            last_referenced_at: 0,
            reference_count: 0,
            decay_eligible: true,
            tags: tags.unwrap_or_default(),
            recurrence_count: 0,
            last_ref_snapshot: 0,
        };
        let pd = plugin_data.map(|d| from_py::<serde_json::Value>(d)).transpose()?;
        let node = ainl_memory::AinlMemoryNode {
            id: Uuid::new_v4(),
            memory_category: ainl_memory::MemoryCategory::Semantic,
            importance_score: confidence,
            agent_id: agent_id.to_string(),
            project_id: None,
            node_type: AinlNodeType::Semantic { semantic },
            edges: Vec::new(),
            plugin_data: pd,
        };
        let id = node.id;
        self.lock_inner()?.write_node(&node)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        Ok(id.to_string())
    }

    /// Write a Failure node. Returns the node UUID string.
    #[pyo3(signature = (agent_id, message, source="plugin", tool_name=None, plugin_data=None))]
    fn write_failure(
        &self,
        agent_id: &str,
        message: &str,
        source: &str,
        tool_name: Option<&str>,
        plugin_data: Option<&Bound<'_, pyo3::PyAny>>,
    ) -> PyResult<String> {
        use ainl_memory::node::{AinlNodeType, FailureNode};
        let failure = FailureNode {
            recorded_at: chrono::Utc::now().timestamp(),
            source: source.to_string(),
            tool_name: tool_name.map(str::to_string),
            source_namespace: Some("plugin".to_string()),
            source_tool: tool_name.map(str::to_string),
            message: message.to_string(),
            session_id: None,
        };
        let pd = plugin_data.map(|d| from_py::<serde_json::Value>(d)).transpose()?;
        let node = ainl_memory::AinlMemoryNode {
            id: Uuid::new_v4(),
            memory_category: ainl_memory::MemoryCategory::Episodic,
            importance_score: 0.8,
            agent_id: agent_id.to_string(),
            project_id: None,
            node_type: AinlNodeType::Failure { failure },
            edges: Vec::new(),
            plugin_data: pd,
        };
        let id = node.id;
        self.lock_inner()?.write_node(&node)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        Ok(id.to_string())
    }

    /// Write a Persona node. Returns the node UUID string.
    #[pyo3(signature = (agent_id, trait_name, strength, plugin_data=None))]
    fn write_persona(
        &self,
        agent_id: &str,
        trait_name: &str,
        strength: f32,
        plugin_data: Option<&Bound<'_, pyo3::PyAny>>,
    ) -> PyResult<String> {
        use ainl_memory::node::{AinlNodeType, PersonaLayer, PersonaNode, PersonaSource};
        let persona = PersonaNode {
            trait_name: trait_name.to_string(),
            strength: strength.clamp(0.0, 1.0),
            learned_from: Vec::new(),
            layer: PersonaLayer::Base,
            source: PersonaSource::Evolved,
            strength_floor: 0.0,
            locked: false,
            relevance_score: strength,
            provenance_episode_ids: Vec::new(),
            evolution_log: Vec::new(),
            axis_scores: std::collections::HashMap::new(),
            evolution_cycle: 0,
            last_evolved: String::new(),
            agent_id: agent_id.to_string(),
            dominant_axes: Vec::new(),
        };
        let pd = plugin_data.map(|d| from_py::<serde_json::Value>(d)).transpose()?;
        let node = ainl_memory::AinlMemoryNode {
            id: Uuid::new_v4(),
            memory_category: ainl_memory::MemoryCategory::Persona,
            importance_score: strength,
            agent_id: agent_id.to_string(),
            project_id: None,
            node_type: AinlNodeType::Persona { persona },
            edges: Vec::new(),
            plugin_data: pd,
        };
        let id = node.id;
        self.lock_inner()?.write_node(&node)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        Ok(id.to_string())
    }

    /// Write a Procedural (pattern) node. Returns the node UUID string.
    #[pyo3(signature = (agent_id, pattern_name, tool_sequence=None, success_count=0, plugin_data=None))]
    fn write_procedural(
        &self,
        agent_id: &str,
        pattern_name: &str,
        tool_sequence: Option<Vec<String>>,
        success_count: u32,
        plugin_data: Option<&Bound<'_, pyo3::PyAny>>,
    ) -> PyResult<String> {
        use ainl_memory::node::{AinlNodeType, ProceduralNode, ProcedureType};
        let procedural = ProceduralNode {
            pattern_name: pattern_name.to_string(),
            compiled_graph: Vec::new(),
            tool_sequence: tool_sequence.unwrap_or_default(),
            confidence: None,
            procedure_type: ProcedureType::ToolSequence,
            trigger_conditions: Vec::new(),
            success_count,
            failure_count: 0,
            success_rate: if success_count > 0 { 1.0 } else { 0.0 },
            last_invoked_at: 0,
            reinforcement_episode_ids: Vec::new(),
            suppression_episode_ids: Vec::new(),
            patch_version: 0,
            fitness: Some(success_count as f32 / (success_count as f32 + 1.0)),
            declared_reads: Vec::new(),
            retired: false,
            label: pattern_name.to_string(),
            trace_id: None,
            pattern_observation_count: 0,
            prompt_eligible: true,
        };
        let pd = plugin_data.map(|d| from_py::<serde_json::Value>(d)).transpose()?;
        let node = ainl_memory::AinlMemoryNode {
            id: Uuid::new_v4(),
            memory_category: ainl_memory::MemoryCategory::Procedural,
            importance_score: success_count as f32 / (success_count as f32 + 1.0),
            agent_id: agent_id.to_string(),
            project_id: None,
            node_type: AinlNodeType::Procedural { procedural },
            edges: Vec::new(),
            plugin_data: pd,
        };
        let id = node.id;
        self.lock_inner()?.write_node(&node)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        Ok(id.to_string())
    }

    // ── Anchored summary (prompt compression) ──────────────────────────────

    /// Upsert a compressed context summary for `agent_id`.
    /// Returns the stable node UUID string (same for repeated calls with same agent_id).
    fn upsert_anchored_summary(&self, agent_id: &str, summary_payload: &str) -> PyResult<String> {
        let id = anchored_summary_id(agent_id);
        let semantic = SemanticNode {
            fact: summary_payload.to_string(),
            confidence: 1.0,
            source_turn_id: id,
            topic_cluster: None,
            source_episode_id: String::new(),
            contradiction_ids: Vec::new(),
            last_referenced_at: chrono::Utc::now().timestamp() as u64,
            reference_count: 0,
            decay_eligible: false,
            tags: vec![ANCHORED_SUMMARY_TAG.to_string()],
            recurrence_count: 0,
            last_ref_snapshot: 0,
        };
        let node = AinlMemoryNode {
            id,
            memory_category: MemoryCategory::Semantic,
            importance_score: 1.0,
            agent_id: agent_id.to_string(),
            project_id: None,
            node_type: AinlNodeType::Semantic { semantic },
            edges: Vec::new(),
            plugin_data: None,
        };
        self.lock_inner()?
            .write_node(&node)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        Ok(id.to_string())
    }

    /// Fetch the latest anchored-summary payload for `agent_id`. Returns None if absent.
    fn fetch_anchored_summary(&self, agent_id: &str) -> PyResult<Option<String>> {
        let id = anchored_summary_id(agent_id);
        let node = self
            .lock_inner()?
            .read_node(id)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        Ok(node.and_then(|n| match n.node_type {
            AinlNodeType::Semantic { semantic } => Some(semantic.fact),
            _ => None,
        }))
    }

    /// Patch the plugin_data field of an existing node. Merges with existing plugin_data.
    fn patch_plugin_data(
        &self,
        node_id: &str,
        updates: &Bound<'_, pyo3::PyAny>,
    ) -> PyResult<()> {
        let id = Uuid::parse_str(node_id)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        let updates_val: serde_json::Value = from_py(updates)?;

        let guard = self.lock_inner()?;
        let existing = guard.read_node(id)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        if let Some(mut node) = existing {
            let merged = match node.plugin_data.take() {
                Some(serde_json::Value::Object(mut m)) => {
                    if let serde_json::Value::Object(u) = updates_val {
                        m.extend(u);
                    }
                    serde_json::Value::Object(m)
                }
                _ => updates_val,
            };
            node.plugin_data = Some(merged);
            guard.write_node(&node)
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        }
        Ok(())
    }
}

#[cfg(test)]
mod poison_tests {
    use super::*;
    use std::sync::Arc;
    use std::thread;
    use tempfile::tempdir;

    /// A panicking thread that holds the lock must leave the mutex poisoned;
    /// our `lock_inner` helper must surface this as a catchable PyRuntimeError
    /// rather than panicking the host process when the next call comes in.
    #[test]
    fn lock_inner_returns_pyerr_when_mutex_poisoned() {
        pyo3::prepare_freethreaded_python();
        let tmp = tempdir().expect("tempdir");
        let db_path = tmp.path().join("poison.db");

        let store = AinlNativeStore::open(db_path.to_str().unwrap())
            .expect("open store");
        let store = Arc::new(store);

        // Poison the mutex from another thread.
        let poisoner = Arc::clone(&store);
        let _ = thread::spawn(move || {
            let _guard = poisoner.inner.lock().unwrap();
            panic!("intentional panic to poison the mutex");
        })
        .join();

        // The mutex is now poisoned. lock_inner must convert that into a
        // PyResult::Err, not panic.
        let result = store.lock_inner();
        assert!(result.is_err(), "expected PyResult::Err for poisoned mutex");
        let err_text = format!("{}", result.err().unwrap());
        assert!(
            err_text.contains("poisoned"),
            "error message should mention poisoning, got: {}",
            err_text
        );
    }
}
