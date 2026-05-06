//! PyO3 bindings for ainl-persona EvolutionEngine.

use ainl_memory::store::SqliteGraphStore;
use ainl_persona::{EvolutionEngine, PersonaSnapshot};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::path::Path;

#[pyclass]
pub struct AinlPersonaEngine {
    engine: EvolutionEngine,
}

#[pymethods]
impl AinlPersonaEngine {
    #[new]
    fn new(agent_id: &str) -> Self {
        Self {
            engine: EvolutionEngine::new(agent_id),
        }
    }

    /// Run extract → ingest → write against db_path. Returns snapshot dict.
    fn evolve(&mut self, py: Python<'_>, db_path: &str) -> PyResult<PyObject> {
        let store = SqliteGraphStore::open(Path::new(db_path))
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        let snapshot = self
            .engine
            .evolve(&store)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;
        snapshot_to_py(py, &snapshot)
    }

    /// Return current persona snapshot without writing.
    fn snapshot(&self, py: Python<'_>) -> PyResult<PyObject> {
        snapshot_to_py(py, &self.engine.snapshot())
    }

    /// Apply a correction tick to a named axis.
    /// axis: "instrumentality" | "verbosity" | "persistence" | "systematicity" | "curiosity"
    /// correction: float in -1..1
    fn correction_tick(&mut self, axis_name: &str, correction: f32) -> PyResult<()> {
        let axis = ainl_persona::PersonaAxis::parse(axis_name).ok_or_else(|| {
            pyo3::exceptions::PyValueError::new_err(format!(
                "Unknown PersonaAxis: '{}'. Valid: instrumentality, verbosity, persistence, systematicity, curiosity",
                axis_name
            ))
        })?;
        self.engine.correction_tick(axis, correction);
        Ok(())
    }
}

/// PersonaSnapshot doesn't derive Serialize — convert manually to Python dict.
fn snapshot_to_py(py: Python<'_>, s: &PersonaSnapshot) -> PyResult<PyObject> {
    let d = PyDict::new(py);
    d.set_item("agent_id", &s.agent_id)?;
    d.set_item("captured_at", s.captured_at.to_rfc3339())?;
    let axes = PyDict::new(py);
    for (axis, state) in &s.axes {
        axes.set_item(axis.name().to_lowercase(), state.score)?;
    }
    d.set_item("axes", axes)?;
    Ok(d.into())
}
