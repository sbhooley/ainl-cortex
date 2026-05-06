//! JSON bridge helpers — convert Rust structs ↔ Python dicts via serde_json.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

/// Serialize any serde-serializable value to a Python dict/list/scalar.
pub fn to_py<T: serde::Serialize>(py: Python<'_>, value: &T) -> PyResult<PyObject> {
    let json_str = serde_json::to_string(value)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let json_mod = py.import("json")?;
    json_mod.call_method1("loads", (json_str,)).map(|v| v.into())
}

/// Deserialize a Python dict/list/scalar into a serde-deserializable Rust type.
pub fn from_py<T: serde::de::DeserializeOwned>(obj: &Bound<'_, PyAny>) -> PyResult<T> {
    let py = obj.py();
    let json_mod = py.import("json")?;
    let json_str: String = json_mod
        .call_method1("dumps", (obj,))?
        .extract()?;
    serde_json::from_str(&json_str)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}
