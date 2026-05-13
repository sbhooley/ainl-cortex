//! Environment snapshot reconciliation — native backend implementation.
//!
//! Mirrors mcp_server/memory_reconcile.py for users on the Rust backend.
//! Called from hooks/startup.py when store_backend = "native".
//!
//! Design principles:
//!   - One canonical snapshot node per project, identified by a STABLE UUID derived
//!     from project_id via Uuid::new_v5. write_node() is upsert-by-ID so there is
//!     never more than one active snapshot and stale nodes never accumulate.
//!   - O(1) lookup: store.read_node(stable_id) instead of find_by_type scan.
//!   - Path normalization via std::fs::canonicalize before comparison so symlinks
//!     and trailing slashes never produce false positives.
//!   - Always non-fatal: errors return stale_found=false rather than propagating.

use ainl_memory::{
    node::{AinlNodeType, MemoryCategory, SemanticNode},
    store::{GraphStore, SqliteGraphStore},
    AinlMemoryNode,
};
use chrono::Utc;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::path::Path;
use uuid::Uuid;

const ENV_CLUSTER: &str = "environment_snapshot";
const ENV_CLUSTER_LEGACY: &str = "environment_snapshot:legacy";

// ── Stable node identity ──────────────────────────────────────────────────────

/// Deterministic UUID for this project's env snapshot.
///
/// Using Uuid::new_v5 (SHA-1 namespace hash) guarantees exactly one snapshot
/// node per project. write_node() is an upsert, so the node is updated in place.
fn snapshot_node_id(project_id: &str) -> Uuid {
    Uuid::new_v5(
        &Uuid::NAMESPACE_OID,
        format!("env_snapshot:{}", project_id).as_bytes(),
    )
}

// ── Path normalization ────────────────────────────────────────────────────────

/// Canonicalize plugin_root: resolve symlinks, strip trailing slashes.
/// Falls back to trimming trailing slashes if the path does not exist.
fn normalize_root(plugin_root: &str) -> String {
    std::fs::canonicalize(plugin_root)
        .map(|p| p.to_string_lossy().into_owned())
        .unwrap_or_else(|_| plugin_root.trim_end_matches('/').to_string())
}

// ── fact string (must match Python twin exactly) ──────────────────────────────

fn fact_str(plugin_name: &str, plugin_root: &str, config_backend: &str) -> String {
    format!(
        "environment_snapshot plugin_reference: plugin={} path={} backend={}",
        plugin_name, plugin_root, config_backend
    )
}

// ── Snapshot read / write ─────────────────────────────────────────────────────

/// O(1) lookup: read by stable UUID, then validate topic_cluster.
fn find_env_snapshot(store: &SqliteGraphStore, project_id: &str) -> Option<AinlMemoryNode> {
    let id = snapshot_node_id(project_id);
    store
        .read_node(id)
        .ok()
        .flatten()
        .filter(|n| {
            n.project_id.as_deref() == Some(project_id)
                && matches!(&n.node_type, AinlNodeType::Semantic { semantic }
                    if semantic.topic_cluster.as_deref() == Some(ENV_CLUSTER))
        })
}

fn write_env_snapshot(
    store: &SqliteGraphStore,
    project_id: &str,
    plugin_root: &str,
    plugin_name: &str,
    config_backend: &str,
    timestamp: i64,
    changes: &[String],
) -> Uuid {
    let id = snapshot_node_id(project_id);
    let fact = fact_str(plugin_name, plugin_root, config_backend);

    let last_change = if !changes.is_empty() {
        serde_json::json!({
            "changes": changes,
            "changed_at": timestamp,
        })
    } else {
        serde_json::Value::Null
    };

    let sem = SemanticNode {
        fact,
        confidence: 1.0,
        source_turn_id: Uuid::new_v4(),
        topic_cluster: Some(ENV_CLUSTER.to_string()),
        source_episode_id: String::new(),
        contradiction_ids: Vec::new(),
        last_referenced_at: timestamp as u64,
        reference_count: 0,
        decay_eligible: false,
        tags: vec![
            "auto_env_snapshot".to_string(),
            "plugin_reference".to_string(),
            "environment".to_string(),
        ],
        recurrence_count: 0,
        last_ref_snapshot: 0,
    };
    let node = AinlMemoryNode {
        id,
        memory_category: MemoryCategory::Semantic,
        importance_score: 1.0,
        agent_id: "claude-code".to_string(),
        project_id: Some(project_id.to_string()),
        node_type: AinlNodeType::Semantic { semantic: sem },
        edges: Vec::new(),
        plugin_data: Some(serde_json::json!({
            "plugin_root": plugin_root,
            "plugin_name": plugin_name,
            "config_backend": config_backend,
            "snapshot_type": "environment",
            "captured_at": timestamp,
            "last_change": last_change,
        })),
    };
    let _ = store.write_node(&node);
    id
}

// ── Legacy cleanup ────────────────────────────────────────────────────────────

/// One-time cleanup of phantom snapshot nodes written by pre-fix code.
/// Only called on the first session where no stable-UUID snapshot exists yet.
fn cleanup_legacy_snapshots(store: &SqliteGraphStore, project_id: &str, keep_id: Uuid) {
    let all_semantic = match store.find_by_type("Semantic") {
        Ok(v) => v,
        Err(_) => return,
    };
    for node in all_semantic {
        if node.id == keep_id {
            continue;
        }
        if node.project_id.as_deref() != Some(project_id) {
            continue;
        }
        let is_old_snapshot = matches!(&node.node_type, AinlNodeType::Semantic { semantic }
            if matches!(
                semantic.topic_cluster.as_deref(),
                Some("environment_snapshot") | Some("environment_snapshot:stale")
            ));
        if is_old_snapshot {
            // Overwrite with legacy cluster so it's excluded from future lookups.
            if let AinlNodeType::Semantic { semantic: old } = &node.node_type {
                let legacy_sem = SemanticNode {
                    fact: old.fact.clone(),
                    confidence: old.confidence,
                    source_turn_id: old.source_turn_id,
                    topic_cluster: Some(ENV_CLUSTER_LEGACY.to_string()),
                    source_episode_id: old.source_episode_id.clone(),
                    contradiction_ids: old.contradiction_ids.clone(),
                    last_referenced_at: old.last_referenced_at,
                    reference_count: old.reference_count,
                    decay_eligible: true,
                    tags: old.tags.clone(),
                    recurrence_count: old.recurrence_count,
                    last_ref_snapshot: old.last_ref_snapshot,
                };
                let legacy_node = AinlMemoryNode {
                    id: node.id,
                    memory_category: MemoryCategory::Semantic,
                    importance_score: node.importance_score,
                    agent_id: node.agent_id.clone(),
                    project_id: node.project_id.clone(),
                    node_type: AinlNodeType::Semantic { semantic: legacy_sem },
                    edges: Vec::new(),
                    plugin_data: node.plugin_data.clone(),
                };
                let _ = store.write_node(&legacy_node);
            }
        }
    }
}

// ── Public PyO3 function ──────────────────────────────────────────────────────

/// Reconcile stored environment snapshot against current observable state.
///
/// db_path:        absolute path to ainl_native.db
/// project_id:     Claude Code project hash
/// plugin_root:    current plugin root directory (CLAUDE_PLUGIN_ROOT or __file__ fallback)
/// config_backend: "python" or "native"
///
/// Returns dict: {stale_found: bool, changes: [str], snapshot_id: str}
/// Non-fatal: errors return stale_found=false.
#[pyfunction]
pub fn reconcile_environment(
    py: Python<'_>,
    db_path: &str,
    project_id: &str,
    plugin_root: &str,
    config_backend: &str,
) -> PyResult<PyObject> {
    let result = PyDict::new(py);

    // Open (or create) the database. Unlike session_context we must proceed even
    // when the DB does not yet exist so we can write the initial snapshot.
    let store = match SqliteGraphStore::open(Path::new(db_path)) {
        Ok(s) => s,
        Err(_) => {
            result.set_item("stale_found", false)?;
            result.set_item("changes", Vec::<String>::new())?;
            result.set_item("snapshot_id", "")?;
            return Ok(result.into());
        }
    };

    let now = Utc::now().timestamp();
    let normalized_root = normalize_root(plugin_root);
    let plugin_name = Path::new(&normalized_root)
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or(&normalized_root);

    let existing = find_env_snapshot(&store, project_id);
    let stable_id = snapshot_node_id(project_id);
    let mut changes: Vec<String> = Vec::new();

    if existing.is_none() {
        // First session with fixed code: clean up any legacy phantom snapshots.
        cleanup_legacy_snapshots(&store, project_id, stable_id);
    } else if let Some(ref node) = existing {
        if let Some(ref pd) = node.plugin_data {
            let stored_name = pd.get("plugin_name").and_then(|v| v.as_str()).unwrap_or("");
            let stored_root = pd.get("plugin_root").and_then(|v| v.as_str()).unwrap_or("");
            let stored_backend = pd
                .get("config_backend")
                .and_then(|v| v.as_str())
                .unwrap_or("");

            if !stored_name.is_empty() && stored_name != plugin_name {
                changes.push(format!("plugin renamed: {} → {}", stored_name, plugin_name));
            }
            if !stored_root.is_empty() && stored_root != normalized_root {
                changes.push(format!(
                    "plugin path changed: {} → {}",
                    stored_root, normalized_root
                ));
            }
            if !stored_backend.is_empty() && stored_backend != config_backend {
                changes.push(format!(
                    "backend changed: {} → {}",
                    stored_backend, config_backend
                ));
            }
        }
    }

    let new_id = if existing.is_none() || !changes.is_empty() {
        write_env_snapshot(
            &store,
            project_id,
            &normalized_root,
            plugin_name,
            config_backend,
            now,
            &changes,
        )
    } else {
        stable_id
    };

    result.set_item("stale_found", !changes.is_empty())?;
    result.set_item("changes", changes)?;
    result.set_item("snapshot_id", new_id.to_string())?;
    Ok(result.into())
}
