//! PyO3 bindings for ainl-context-freshness pure functions.

use ainl_context_freshness::{
    can_execute_with_context, evaluate_freshness, FreshnessInputs,
};
use ainl_contracts::ContextFreshness;
use pyo3::prelude::*;

/// Evaluate context freshness from inputs.
/// index_stale: None = unknown, True = stale, False = fresh
/// Returns "Fresh", "Stale", or "Unknown".
#[pyfunction]
#[pyo3(signature = (index_stale=None, unknown=false))]
pub fn check_freshness(
    index_stale: Option<bool>,
    unknown: bool,
) -> String {
    let inputs = FreshnessInputs {
        index_stale_vs_head: index_stale,
        unknown,
    };
    let freshness = evaluate_freshness(&inputs);
    match freshness {
        ContextFreshness::Fresh => "Fresh".to_string(),
        ContextFreshness::Stale => "Stale".to_string(),
        ContextFreshness::Unknown => "Unknown".to_string(),
    }
}

/// Gate tool execution based on freshness state.
/// strict: if True, apply strict policy (block on Stale), else balanced.
/// repo_intel_ready: whether repo-intel data is available.
/// Returns True if execution is allowed.
#[pyfunction]
#[pyo3(signature = (freshness_str, strict=false, repo_intel_ready=false))]
pub fn can_execute(
    freshness_str: &str,
    strict: bool,
    repo_intel_ready: bool,
) -> bool {
    let freshness = match freshness_str {
        "Fresh" => ContextFreshness::Fresh,
        "Stale" => ContextFreshness::Stale,
        _ => ContextFreshness::Unknown,
    };
    can_execute_with_context(freshness, strict, repo_intel_ready)
}
