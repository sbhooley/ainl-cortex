//! ainl_native — PyO3 bindings for ainl-graph-memory plugin.
//!
//! JSON-in/JSON-out bridge: Python sends/receives plain dicts via serde_json.
//! No complex type mapping needed.

mod convert;
mod freshness;
mod persona;
mod procedure;
mod session;
mod store;
mod tagger;
mod trajectory;

use pyo3::prelude::*;

#[pymodule]
fn ainl_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Store (graph memory CRUD + traversal)
    m.add_class::<store::AinlNativeStore>()?;

    // Persona evolution
    m.add_class::<persona::AinlPersonaEngine>()?;

    // Trajectory builder (per-tool-call step capture)
    m.add_class::<trajectory::AinlTrajectoryBuilder>()?;

    // Stateless functions
    m.add_function(wrap_pyfunction!(tagger::tag_turn, m)?)?;
    m.add_function(wrap_pyfunction!(tagger::tag_message, m)?)?;
    m.add_function(wrap_pyfunction!(tagger::infer_topics, m)?)?;

    m.add_function(wrap_pyfunction!(procedure::distill_procedure, m)?)?;
    m.add_function(wrap_pyfunction!(procedure::score_reuse, m)?)?;
    m.add_function(wrap_pyfunction!(procedure::cluster_experiences, m)?)?;
    m.add_function(wrap_pyfunction!(procedure::build_experience_bundle, m)?)?;

    m.add_function(wrap_pyfunction!(freshness::check_freshness, m)?)?;
    m.add_function(wrap_pyfunction!(freshness::can_execute, m)?)?;

    // Session lifecycle (consolidated entry points for hooks)
    m.add_function(wrap_pyfunction!(session::finalize_session, m)?)?;
    m.add_function(wrap_pyfunction!(session::session_context, m)?)?;
    m.add_function(wrap_pyfunction!(session::recall_context, m)?)?;

    Ok(())
}
