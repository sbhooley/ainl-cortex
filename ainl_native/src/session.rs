//! Consolidated session lifecycle entry points — one call per hook instead of N calls.
//!
//! finalize_session: Stop hook — episode, trajectory, persona, procedure learning, summary.
//! session_context:  SessionStart hook — anchored summary + freshness gate.

use ainl_context_freshness::{can_execute_with_context, evaluate_freshness, FreshnessInputs};
use ainl_contracts::{ContextFreshness, TrajectoryOutcome};
use ainl_memory::{
    anchored_summary::{anchored_summary_id, ANCHORED_SUMMARY_TAG},
    node::{AinlNodeType, MemoryCategory, ProceduralNode, ProcedureType, SemanticNode},
    store::{GraphStore, SqliteGraphStore},
    AinlMemoryNode,
};
use ainl_persona::EvolutionEngine;
use ainl_procedure_learning::DistillPolicy;
use ainl_trajectory::TrajectoryDraft;
use chrono::Utc;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use serde::Deserialize;
use std::path::Path;
use uuid::Uuid;

// ── Input schema ─────────────────────────────────────────────────────────────

#[derive(Deserialize)]
struct SessionInput {
    #[serde(default)]
    tool_calls: Vec<String>,
    #[serde(default)]
    files_touched: Vec<String>,
    #[serde(default)]
    #[allow(dead_code)]
    had_errors: bool,
    #[serde(default)]
    task_summary: String,
    #[serde(default)]
    outcome: String,
    #[serde(default)]
    capture_count: usize,
}

// ── Public PyO3 functions ─────────────────────────────────────────────────────

/// Consolidated Stop hook entry point.
///
/// db_path:        absolute path to ainl_native.db
/// project_id:     Claude Code project hash (used as session_id / project_id)
/// session_json:   JSON string matching SessionInput above
/// step_file_path: optional JSONL file of buffered trajectory steps
///
/// Returns dict: {episode_id, trajectory_steps, procedures_promoted, summary_saved,
///                persona_snapshot?}
/// All fields are present; errors in sub-operations are swallowed (non-fatal).
#[pyfunction]
#[pyo3(signature = (db_path, project_id, session_json, step_file_path=None))]
pub fn finalize_session(
    py: Python<'_>,
    db_path: &str,
    project_id: &str,
    session_json: &str,
    step_file_path: Option<&str>,
) -> PyResult<PyObject> {
    let input: SessionInput = serde_json::from_str(session_json)
        .unwrap_or_else(|_| SessionInput {
            tool_calls: vec![],
            files_touched: vec![],
            had_errors: false,
            task_summary: String::new(),
            outcome: "success".to_string(),
            capture_count: 0,
        });

    if let Some(parent) = Path::new(db_path).parent() {
        let _ = std::fs::create_dir_all(parent);
    }

    let result = PyDict::new(py);

    let store = match SqliteGraphStore::open(Path::new(db_path)) {
        Ok(s) => s,
        Err(e) => {
            result.set_item("error", e.to_string())?;
            result.set_item("episode_id", "")?;
            result.set_item("trajectory_steps", 0usize)?;
            result.set_item("procedures_promoted", 0usize)?;
            result.set_item("summary_saved", false)?;
            return Ok(result.into());
        }
    };

    let timestamp = Utc::now().timestamp();

    // 1. Record episode node
    let turn_id = Uuid::new_v4();
    let episode_node = AinlMemoryNode::new_episode(
        turn_id,
        timestamp,
        input.tool_calls.clone(),
        None,
        None,
    );
    let episode_id = episode_node.id;
    let _ = store.write_node(&episode_node);

    // 2. Semantic tagging — tag the turn and store top tags as a semantic node
    let tags = ainl_semantic_tagger::tag_turn(&input.task_summary, None, &input.tool_calls);
    let tag_values: Vec<String> = serde_json::to_value(&tags)
        .ok()
        .and_then(|v| v.as_array().cloned())
        .unwrap_or_default()
        .iter()
        .take(6)
        .filter_map(|t| t.get("value").and_then(|v| v.as_str()).map(str::to_string))
        .collect();

    if !tag_values.is_empty() {
        let sem = SemanticNode {
            fact: format!("Episode tags: {}", tag_values.join(", ")),
            confidence: 0.9,
            source_turn_id: turn_id,
            topic_cluster: None,
            source_episode_id: String::new(),
            contradiction_ids: Vec::new(),
            last_referenced_at: timestamp as u64,
            reference_count: 0,
            decay_eligible: true,
            tags: tag_values.clone(),
            recurrence_count: 0,
            last_ref_snapshot: 0,
        };
        let sem_node = AinlMemoryNode {
            id: Uuid::new_v4(),
            memory_category: MemoryCategory::Semantic,
            importance_score: 0.9,
            agent_id: "claude-code".to_string(),
            project_id: Some(project_id.to_string()),
            node_type: AinlNodeType::Semantic { semantic: sem },
            edges: Vec::new(),
            plugin_data: None,
        };
        let _ = store.write_node(&sem_node);
    }

    // 3. Trajectory flush
    let traj_steps = flush_trajectory(
        &store,
        episode_id,
        project_id,
        &input.outcome,
        step_file_path,
        timestamp,
    );

    // 4. Procedure learning
    let procedures_promoted = run_procedure_learning(
        &store,
        project_id,
        timestamp - 30 * 86400,
    );

    // 5. Persona evolution (opens second connection — EvolutionEngine needs its own store)
    let persona_snapshot = run_persona_evolution(db_path);

    // 6. Anchored summary
    let summary_saved = save_anchored_summary(
        &store,
        &input,
        &tag_values,
        project_id,
        timestamp,
    );

    result.set_item("episode_id", episode_id.to_string())?;
    result.set_item("trajectory_steps", traj_steps)?;
    result.set_item("procedures_promoted", procedures_promoted)?;
    result.set_item("summary_saved", summary_saved)?;

    if let Some(snap_val) = persona_snapshot {
        let json_mod = py.import("json")?;
        let snap_str = serde_json::to_string(&snap_val).unwrap_or_default();
        let snap_obj = json_mod.call_method1("loads", (snap_str,))?;
        result.set_item("persona_snapshot", snap_obj)?;
    }

    Ok(result.into())
}

/// Consolidated SessionStart entry point.
///
/// Returns dict: {summary_json, freshness, can_execute, age_hours}
/// summary_json is None if no prior session summary exists.
#[pyfunction]
pub fn session_context(
    py: Python<'_>,
    db_path: &str,
    _project_id: &str,
) -> PyResult<PyObject> {
    let result = PyDict::new(py);

    if !Path::new(db_path).exists() {
        result.set_item("summary_json", py.None())?;
        result.set_item("freshness", "Unknown")?;
        result.set_item("can_execute", true)?;
        result.set_item("age_hours", 0.0f64)?;
        return Ok(result.into());
    }

    let store = match SqliteGraphStore::open(Path::new(db_path)) {
        Ok(s) => s,
        Err(_) => {
            result.set_item("summary_json", py.None())?;
            result.set_item("freshness", "Unknown")?;
            result.set_item("can_execute", true)?;
            result.set_item("age_hours", 0.0f64)?;
            return Ok(result.into());
        }
    };

    let raw = fetch_anchored_summary_raw(&store);

    let (age_h, freshness_str, ok) = match &raw {
        Some(payload) => {
            let age_h = compute_age_hours(payload);
            let inputs = FreshnessInputs {
                index_stale_vs_head: Some(age_h > 24.0),
                unknown: false,
            };
            let freshness = evaluate_freshness(&inputs);
            let ok = can_execute_with_context(freshness, false, false);
            let f_str = match freshness {
                ContextFreshness::Fresh => "Fresh",
                ContextFreshness::Stale => "Stale",
                ContextFreshness::Unknown => "Unknown",
            };
            (age_h, f_str, ok)
        }
        None => (0.0, "Unknown", true),
    };

    match raw {
        Some(payload) => result.set_item("summary_json", payload)?,
        None => result.set_item("summary_json", py.None())?,
    }
    result.set_item("freshness", freshness_str)?;
    result.set_item("can_execute", ok)?;
    result.set_item("age_hours", age_h)?;
    Ok(result.into())
}

// ── Private helpers ───────────────────────────────────────────────────────────

fn flush_trajectory(
    store: &SqliteGraphStore,
    episode_id: Uuid,
    project_id: &str,
    outcome_str: &str,
    step_file_path: Option<&str>,
    timestamp: i64,
) -> usize {
    let path = match step_file_path {
        Some(p) if Path::new(p).exists() => p,
        _ => return 0,
    };

    let content = match std::fs::read_to_string(path) {
        Ok(c) => c,
        Err(_) => return 0,
    };
    let _ = std::fs::remove_file(path);

    let steps: Vec<serde_json::Value> = content
        .lines()
        .filter(|l| !l.trim().is_empty())
        .filter_map(|l| serde_json::from_str(l).ok())
        .collect();

    let count = steps.len();
    if count == 0 {
        return 0;
    }

    // Map Python stop.py outcome strings to canonical trajectory outcome strings
    let canonical_outcome = match outcome_str.to_lowercase().as_str() {
        "success" => "success",
        "partial" | "partial_success" => "partial_success",
        "error" | "failure" | "failed" => "failure",
        "aborted" | "abort" => "aborted",
        _ => "partial_success",
    };

    let record_val = serde_json::json!({
        "id": Uuid::new_v4().to_string(),
        "episode_id": episode_id.to_string(),
        "agent_id": "claude-code",
        "session_id": project_id,
        "project_id": project_id,
        "recorded_at": timestamp,
        "outcome": canonical_outcome,
        "duration_ms": 0u64,
        "steps": steps,
    });

    if let Ok(row) = serde_json::from_value::<ainl_memory::trajectory_table::TrajectoryDetailRecord>(record_val) {
        let _ = store.insert_trajectory_detail(&row);
    }

    count
}

/// Map a TrajectoryDetailRecord outcome (enum) to a TrajectoryDraft outcome (same enum).
fn map_traj_outcome(o: &TrajectoryOutcome) -> TrajectoryOutcome {
    match o {
        TrajectoryOutcome::Success => TrajectoryOutcome::Success,
        TrajectoryOutcome::PartialSuccess => TrajectoryOutcome::PartialSuccess,
        TrajectoryOutcome::Failure => TrajectoryOutcome::Failure,
        TrajectoryOutcome::Aborted => TrajectoryOutcome::Aborted,
    }
}

fn run_procedure_learning(
    store: &SqliteGraphStore,
    project_id: &str,
    since_ts: i64,
) -> usize {
    let records = match store.list_trajectories_for_agent("claude-code", 100, Some(since_ts)) {
        Ok(r) => r,
        Err(_) => return 0,
    };
    if records.len() < 2 {
        return 0;
    }

    let drafts: Vec<TrajectoryDraft> = records
        .iter()
        .filter_map(|r| {
            let outcome = map_traj_outcome(&r.outcome);
            let mut draft = TrajectoryDraft::new(r.episode_id, outcome);
            draft.session_id = r.session_id.clone();
            draft.project_id = r.project_id.clone().or_else(|| Some(project_id.to_string()));
            draft.duration_ms = r.duration_ms;
            Some(draft)
        })
        .collect();

    if drafts.len() < 2 {
        return 0;
    }

    let clusters = ainl_trajectory::cluster_experiences(&drafts);
    if clusters.is_empty() {
        return 0;
    }

    let policy = DistillPolicy {
        min_observations: 2,
        min_fitness: 0.5,
        require_success: true,
    };

    let mut promoted = 0;
    for cluster in &clusters {
        let bundle = ainl_trajectory::build_experience_bundle(cluster);
        let artifact = match ainl_procedure_learning::distill_procedure(&bundle, &policy) {
            Ok(a) => a,
            Err(_) => continue,
        };

        // Access artifact fields via serde_json::Value (ProcedureArtifact may have private fields)
        let artifact_val = match serde_json::to_value(&artifact) {
            Ok(v) => v,
            Err(_) => continue,
        };
        let title = artifact_val
            .get("title")
            .and_then(|v| v.as_str())
            .or_else(|| artifact_val.get("id").and_then(|v| v.as_str()))
            .unwrap_or("procedure")
            .to_string();
        let required_tools: Vec<String> = artifact_val
            .get("required_tools")
            .and_then(|v| serde_json::from_value(v.clone()).ok())
            .unwrap_or_default();
        let observation_count = artifact_val
            .get("observation_count")
            .and_then(|v| v.as_u64())
            .unwrap_or(0) as u32;
        let fitness = artifact_val
            .get("fitness")
            .and_then(|v| v.as_f64())
            .map(|f| f as f32)
            .unwrap_or(0.5);

        let proc_node = ProceduralNode {
            pattern_name: title.clone(),
            compiled_graph: Vec::new(),
            tool_sequence: required_tools.clone(),
            confidence: Some(fitness),
            procedure_type: ProcedureType::ToolSequence,
            trigger_conditions: Vec::new(),
            success_count: observation_count,
            failure_count: 0,
            success_rate: fitness,
            last_invoked_at: 0,
            reinforcement_episode_ids: Vec::new(),
            suppression_episode_ids: Vec::new(),
            patch_version: 0,
            fitness: Some(fitness),
            declared_reads: Vec::new(),
            retired: false,
            label: title.clone(),
            trace_id: None,
            pattern_observation_count: observation_count,
            prompt_eligible: true,
        };
        let node = AinlMemoryNode {
            id: Uuid::new_v4(),
            memory_category: MemoryCategory::Procedural,
            importance_score: fitness,
            agent_id: "claude-code".to_string(),
            project_id: Some(project_id.to_string()),
            node_type: AinlNodeType::Procedural {
                procedural: proc_node,
            },
            edges: Vec::new(),
            plugin_data: None,
        };
        let _ = store.write_node(&node);
        promoted += 1;
    }

    promoted
}

fn run_persona_evolution(db_path: &str) -> Option<serde_json::Value> {
    // Open a second SqliteGraphStore connection — EvolutionEngine::evolve needs its own store
    let store = SqliteGraphStore::open(Path::new(db_path)).ok()?;
    let mut engine = EvolutionEngine::new("claude-code");
    let snapshot = engine.evolve(&store).ok()?;

    // PersonaSnapshot doesn't derive Serialize — build JSON manually
    let mut axes = serde_json::Map::new();
    for (axis, state) in &snapshot.axes {
        axes.insert(
            axis.name().to_lowercase().to_string(),
            serde_json::Value::from(state.score as f64),
        );
    }

    Some(serde_json::json!({
        "agent_id": &snapshot.agent_id,
        "captured_at": snapshot.captured_at.to_rfc3339(),
        "axes": serde_json::Value::Object(axes),
    }))
}

fn save_anchored_summary(
    store: &SqliteGraphStore,
    input: &SessionInput,
    tag_values: &[String],
    project_id: &str,
    timestamp: i64,
) -> bool {
    let file_names: Vec<String> = input
        .files_touched
        .iter()
        .take(8)
        .map(|f| {
            Path::new(f)
                .file_name()
                .and_then(|n| n.to_str())
                .unwrap_or(f.as_str())
                .to_string()
        })
        .collect();

    let payload = match serde_json::to_string(&serde_json::json!({
        "schema_version": 1,
        "task_summary": &input.task_summary,
        "outcome": &input.outcome,
        "tools_used": &input.tool_calls[..input.tool_calls.len().min(12)],
        "files_touched": file_names,
        "semantic_tags": tag_values,
        "capture_count": input.capture_count,
        "session_ts": timestamp,
        "project_id": project_id,
    })) {
        Ok(p) => p,
        Err(_) => return false,
    };

    let id = anchored_summary_id("claude-code");
    let semantic = SemanticNode {
        fact: payload,
        confidence: 1.0,
        source_turn_id: id,
        topic_cluster: None,
        source_episode_id: String::new(),
        contradiction_ids: Vec::new(),
        last_referenced_at: timestamp as u64,
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
        agent_id: "claude-code".to_string(),
        project_id: None,
        node_type: AinlNodeType::Semantic { semantic },
        edges: Vec::new(),
        plugin_data: None,
    };
    store.write_node(&node).is_ok()
}

fn fetch_anchored_summary_raw(store: &SqliteGraphStore) -> Option<String> {
    let id = anchored_summary_id("claude-code");
    let node = store.read_node(id).ok()??;
    match node.node_type {
        AinlNodeType::Semantic { semantic } => Some(semantic.fact),
        _ => None,
    }
}

fn compute_age_hours(payload: &str) -> f64 {
    let v: serde_json::Value = match serde_json::from_str(payload) {
        Ok(v) => v,
        Err(_) => return 0.0,
    };
    let session_ts = match v.get("session_ts").and_then(|n| n.as_i64()) {
        Some(ts) => ts,
        None => return 0.0,
    };
    let now = Utc::now().timestamp();
    ((now - session_ts).max(0) as f64) / 3600.0
}
