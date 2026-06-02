//! Batch ingest content-knowledge semantic facts (PyO3).

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

#[derive(serde::Deserialize)]
struct IngestInput {
    facts: Vec<String>,
    #[serde(default)]
    tags: Vec<String>,
    #[serde(default)]
    topic_cluster: Option<String>,
    #[serde(default = "default_confidence")]
    confidence: f32,
    #[serde(default)]
    source_kind: String,
}

fn default_confidence() -> f32 {
    0.85
}

fn semantic_id(project_id: &str, fact: &str) -> Uuid {
    let normalized: String = fact.split_whitespace().collect::<Vec<_>>().join(" ");
    let trimmed = &normalized[..normalized.len().min(500)];
    Uuid::new_v5(
        &Uuid::NAMESPACE_OID,
        format!("sem:{project_id}:{trimmed}").as_bytes(),
    )
}

/// ingest_facts(db_path, project_id, payload_json) -> { written, bumped }
#[pyfunction]
#[pyo3(signature = (db_path, project_id, payload_json))]
pub fn ingest_facts(py: Python<'_>, db_path: &str, project_id: &str, payload_json: &str) -> PyResult<PyObject> {
    let result = PyDict::new(py);
    let input: IngestInput = match serde_json::from_str(payload_json) {
        Ok(v) => v,
        Err(e) => {
            result.set_item("error", e.to_string())?;
            result.set_item("written", 0usize)?;
            return Ok(result.into());
        }
    };

    if let Some(parent) = Path::new(db_path).parent() {
        let _ = std::fs::create_dir_all(parent);
    }

    let store = match SqliteGraphStore::open(Path::new(db_path)) {
        Ok(s) => s,
        Err(e) => {
            result.set_item("error", e.to_string())?;
            result.set_item("written", 0usize)?;
            return Ok(result.into());
        }
    };

    let cluster = input
        .topic_cluster
        .unwrap_or_else(|| format!("knowledge:{project_id}"));
    let timestamp = Utc::now().timestamp();
    let mut written = 0usize;
    let mut bumped = 0usize;

    for raw in input.facts.iter().take(40) {
        let fact = raw.trim();
        if fact.len() < 12 {
            continue;
        }
        let id = semantic_id(project_id, fact);
        if store.read_node(id).ok().flatten().is_some() {
            bumped += 1;
            continue;
        }
        let mut tags = vec!["knowledge".to_string()];
        tags.extend(input.tags.clone());
        if !input.source_kind.is_empty() {
            tags.push(format!("source:{}", input.source_kind));
        }
        let sem = SemanticNode {
            fact: fact.to_string(),
            confidence: input.confidence.clamp(0.0, 1.0),
            source_turn_id: Uuid::nil(),
            topic_cluster: Some(cluster.clone()),
            source_episode_id: String::new(),
            contradiction_ids: Vec::new(),
            last_referenced_at: timestamp as u64,
            reference_count: 0,
            decay_eligible: true,
            tags,
            recurrence_count: 1,
            last_ref_snapshot: 0,
        };
        let node = AinlMemoryNode {
            id,
            memory_category: MemoryCategory::Semantic,
            importance_score: input.confidence,
            agent_id: "claude-code".to_string(),
            project_id: Some(project_id.to_string()),
            node_type: AinlNodeType::Semantic { semantic: sem },
            edges: Vec::new(),
            plugin_data: None,
        };
        if store.write_node(&node).is_ok() {
            written += 1;
        }
    }

    result.set_item("written", written)?;
    result.set_item("bumped", bumped)?;
    Ok(result.into())
}
