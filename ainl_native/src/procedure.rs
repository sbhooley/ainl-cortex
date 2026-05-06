//! PyO3 bindings for ainl-procedure-learning stateless functions.

use crate::convert::{from_py, to_py};
use ainl_contracts::ExperienceBundle;
use pyo3::prelude::*;
use pyo3::types::PyDict;

/// Distill an ExperienceBundle dict into a ProcedureArtifact dict.
#[pyfunction]
#[pyo3(signature = (bundle_dict, min_observations=2, min_fitness=0.5, require_success=true))]
pub fn distill_procedure(
    py: Python<'_>,
    bundle_dict: &Bound<'_, pyo3::PyAny>,
    min_observations: u32,
    min_fitness: f32,
    require_success: bool,
) -> PyResult<PyObject> {
    let bundle: ExperienceBundle = from_py(bundle_dict)?;
    let policy = ainl_procedure_learning::DistillPolicy {
        min_observations,
        min_fitness,
        require_success,
    };
    let artifact = ainl_procedure_learning::distill_procedure(&bundle, &policy)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("{:?}", e)))?;
    to_py(py, &artifact)
}

/// Score how well a ProcedureArtifact matches current intent and available tools.
/// Returns a dict with `procedure_id`, `score`, and `reasons` fields.
#[pyfunction]
pub fn score_reuse(
    py: Python<'_>,
    artifact_dict: &Bound<'_, pyo3::PyAny>,
    user_intent: &str,
    available_tools: Vec<String>,
) -> PyResult<PyObject> {
    let artifact: ainl_contracts::ProcedureArtifact = from_py(artifact_dict)?;
    let s = ainl_procedure_learning::score_reuse(&artifact, user_intent, &available_tools);
    // ReuseScore doesn't derive Serialize — build dict manually
    let d = PyDict::new(py);
    d.set_item("procedure_id", &s.procedure_id)?;
    d.set_item("score", s.score)?;
    d.set_item("reasons", &s.reasons)?;
    Ok(d.into())
}

/// Cluster a list of TrajectoryDraft dicts into ExperienceCluster dicts.
/// TrajectoryDraft is in ainl_trajectory (not procedure-learning).
#[pyfunction]
pub fn cluster_experiences(
    py: Python<'_>,
    records_list: &Bound<'_, pyo3::PyAny>,
) -> PyResult<PyObject> {
    let records: Vec<ainl_trajectory::TrajectoryDraft> = from_py(records_list)?;
    let clusters = ainl_trajectory::cluster_experiences(&records);
    to_py(py, &clusters)
}
