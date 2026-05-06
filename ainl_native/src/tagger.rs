//! PyO3 bindings for ainl-semantic-tagger stateless functions.
//!
//! Requires ainl-semantic-tagger built with the "serde" feature so SemanticTag
//! implements Serialize and can be serialized via serde_json.

use crate::convert::to_py;
use pyo3::prelude::*;

/// Tag a full conversation turn (user + optional assistant + tool names).
/// Returns a list of SemanticTag dicts with namespace, value, confidence fields.
#[pyfunction]
pub fn tag_turn(
    py: Python<'_>,
    user: &str,
    assistant: Option<&str>,
    tools: Vec<String>,
) -> PyResult<PyObject> {
    let tags = ainl_semantic_tagger::tag_turn(user, assistant, &tools);
    to_py(py, &tags)
}

/// Tag just the user message for preference/behavior signals.
/// Returns a list of SemanticTag dicts.
#[pyfunction]
pub fn tag_message(py: Python<'_>, user: &str) -> PyResult<PyObject> {
    let tags = ainl_semantic_tagger::tag_user_message(user);
    to_py(py, &tags)
}

/// Extract topic tags from combined text. Returns list of SemanticTag dicts.
#[pyfunction]
pub fn infer_topics(py: Python<'_>, text: &str) -> PyResult<PyObject> {
    let tags = ainl_semantic_tagger::infer_topic_tags(text);
    to_py(py, &tags)
}
