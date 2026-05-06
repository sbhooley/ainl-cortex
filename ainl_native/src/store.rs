//! PyO3 bindings for SqliteGraphStore.
//!
//! All methods return Python dicts/lists via serde_json round-trip.
//!
//! SqliteGraphStore is !Sync due to RefCell in rusqlite::Connection.
//! It IS Send, so Mutex<Store> satisfies PyO3's required Send + Sync.

use crate::convert::{from_py, to_py};
use ainl_memory::{
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
        self.inner
            .lock()
            .unwrap()
            .write_node(&node)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))
    }

    /// Read a node by UUID string. Returns None if not found.
    fn read_node(&self, py: Python<'_>, node_id: &str) -> PyResult<Option<PyObject>> {
        let id = Uuid::parse_str(node_id)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        match self
            .inner
            .lock()
            .unwrap()
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
        let nodes = self
            .inner
            .lock()
            .unwrap()
            .query_episodes_since(since_timestamp, limit)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        to_py(py, &nodes)
    }

    /// Find all nodes of a given type_name. Returns list of dicts.
    fn find_by_type(&self, py: Python<'_>, type_name: &str) -> PyResult<PyObject> {
        let nodes = self
            .inner
            .lock()
            .unwrap()
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
        let nodes = self
            .inner
            .lock()
            .unwrap()
            .walk_edges(id, label)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        to_py(py, &nodes)
    }

    /// Insert a directed edge between two node UUIDs.
    fn insert_edge(&self, from_id: &str, to_id: &str, label: &str) -> PyResult<()> {
        let from = Uuid::parse_str(from_id)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        let to = Uuid::parse_str(to_id)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        self.inner
            .lock()
            .unwrap()
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
        let guard = self.inner.lock().unwrap();
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
        let nodes = self
            .inner
            .lock()
            .unwrap()
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
        let nodes = self
            .inner
            .lock()
            .unwrap()
            .search_all_nodes_fts_for_agent(agent_id, query, project_id, limit)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        to_py(py, &nodes)
    }

    /// Validate graph integrity for one agent. Returns summary dict.
    fn validate_graph(&self, py: Python<'_>, agent_id: &str) -> PyResult<PyObject> {
        let report = self
            .inner
            .lock()
            .unwrap()
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
        self.inner
            .lock()
            .unwrap()
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
            .inner
            .lock()
            .unwrap()
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
        self.inner
            .lock()
            .unwrap()
            .write_node(&node)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        Ok(node_id.to_string())
    }

    /// Export the full agent graph as a snapshot dict.
    fn export_graph(&self, py: Python<'_>, agent_id: &str) -> PyResult<PyObject> {
        let snapshot = self
            .inner
            .lock()
            .unwrap()
            .export_graph(agent_id)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        to_py(py, &snapshot)
    }
}
