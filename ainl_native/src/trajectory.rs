//! PyO3 bindings for ainl-trajectory TrajectoryDraft builder.

use crate::convert::to_py;
use ainl_contracts::{TrajectoryOutcome, TrajectoryStep};
use ainl_trajectory::TrajectoryDraft;
use pyo3::prelude::*;
use uuid::Uuid;
use chrono::Utc;

#[pyclass]
pub struct AinlTrajectoryBuilder {
    draft: TrajectoryDraft,
    started_ms: i64,
}

#[pymethods]
impl AinlTrajectoryBuilder {
    /// Create a new trajectory draft linked to an episode UUID string.
    /// outcome: "success" | "partial_success" | "failure" | "aborted"
    #[new]
    fn new(episode_id: &str, outcome: &str) -> PyResult<Self> {
        let id = Uuid::parse_str(episode_id)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        let o = parse_outcome(outcome)?;
        Ok(Self {
            draft: TrajectoryDraft::new(id, o),
            started_ms: Utc::now().timestamp_millis(),
        })
    }

    /// Push a tool-call step.
    /// tool: adapter name (e.g. "http", "Bash")
    /// operation: operation name (e.g. "GET", "run")
    /// success: whether the call succeeded
    /// error: optional error string
    /// duration_ms: how long it took (0 if unknown)
    #[pyo3(signature = (tool, operation, success, error=None, duration_ms=0))]
    fn push_step(
        &mut self,
        tool: &str,
        operation: &str,
        success: bool,
        error: Option<&str>,
        duration_ms: u64,
    ) {
        let step = TrajectoryStep {
            step_id: Uuid::new_v4().to_string(),
            timestamp_ms: Utc::now().timestamp_millis(),
            adapter: tool.to_string(),
            operation: operation.to_string(),
            inputs_preview: None,
            outputs_preview: None,
            duration_ms,
            success,
            error: error.map(str::to_string),
            vitals: None,
            freshness_at_step: None,
            frame_vars: None,
            tool_telemetry: None,
        };
        self.draft.push_step(step);
    }

    /// Set the session_id for this trajectory.
    fn set_session(&mut self, session_id: &str) {
        self.draft.session_id = session_id.to_string();
    }

    /// Set the project_id for this trajectory.
    fn set_project(&mut self, project_id: &str) {
        self.draft.project_id = Some(project_id.to_string());
    }

    /// Update the outcome field (e.g. finalize as "success" after all steps).
    fn set_outcome(&mut self, outcome: &str) -> PyResult<()> {
        self.draft.outcome = parse_outcome(outcome)?;
        Ok(())
    }

    /// Finalize and return the trajectory as a Python dict.
    fn build(&mut self, py: Python<'_>) -> PyResult<PyObject> {
        let now_ms = Utc::now().timestamp_millis();
        self.draft.duration_ms = (now_ms - self.started_ms).max(0) as u64;
        to_py(py, &self.draft)
    }
}

fn parse_outcome(s: &str) -> PyResult<TrajectoryOutcome> {
    match s.to_lowercase().as_str() {
        "success" => Ok(TrajectoryOutcome::Success),
        "partial_success" | "partial" => Ok(TrajectoryOutcome::PartialSuccess),
        "failure" | "failed" => Ok(TrajectoryOutcome::Failure),
        "aborted" | "abort" => Ok(TrajectoryOutcome::Aborted),
        _ => Err(pyo3::exceptions::PyValueError::new_err(format!(
            "Unknown outcome: '{}'. Valid: success, partial_success, failure, aborted",
            s
        ))),
    }
}
