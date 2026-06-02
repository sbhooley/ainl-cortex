"""
Knowledge capture configuration (artifact ingestion, research, synthesis, recall).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent

_DEFAULTS: Dict[str, Any] = {
    "artifact_ingestion": {
        "enabled": True,
        "suffixes": [".md", ".txt", ".mdx"],
        "plan_name_substrings": ["game_plan", "game-plan", "plan", "research", "mastery"],
        "min_chars": 200,
        "max_file_bytes": 512_000,
        "max_facts_per_artifact": 40,
        "max_fact_chars": 400,
        "min_confidence": 0.55,
    },
    "research_capture": {
        "enabled": True,
        "web_digest_threshold_chars": 800,
        "max_facts_per_session": 25,
        "default_tags": ["research", "knowledge"],
    },
    "session_synthesis": {
        "enabled": True,
        "min_facts": 5,
        "max_facts": 15,
        "trigger_tools": ["web_search", "web_fetch", "write", "edit"],
    },
    "extraction": {
        "llm": {
            "enabled": False,
            "provider": "openrouter",
            "model": "anthropic/claude-3.5-haiku",
            "api_key_env": "OPENROUTER_API_KEY",
            "max_input_chars": 24_000,
            "timeout_s": 25,
            "max_facts": 20,
        },
    },
    "recall": {
        "topical_intent": True,
        "extra_terms": [],
        "topical_fts_limit": 8,
    },
    "claude_memory_bridge": {
        "enabled": False,
        "memory_dir_name": "memory",
        "file_prefix": "reference_",
        "max_facts_per_file": 30,
    },
    "stop_time_budget_ms": 2500,
    "prompt_remember": {
        "enabled": True,
        "min_user_body_chars": 120,
        "max_user_body_chars": 8000,
        "min_assistant_chars": 80,
        "max_assistant_chars": 12000,
        "max_assistant_messages": 2,
        "max_combined_chars": 28000,
        "min_combined_chars": 80,
        "max_facts": 25,
        "max_fact_chars": 400,
        "confidence": 0.88,
        "time_budget_s": 2.0,
        "include_research_capture": True,
        "use_llm_extraction": False,
    },
}


def _load_merged_config() -> Dict[str, Any]:
    try:
        from .config_loader import load_config_files

        return load_config_files(_PLUGIN_ROOT)
    except Exception:
        try:
            from config_loader import load_config_files

            return load_config_files(_PLUGIN_ROOT)
        except Exception:
            return {}


def get_knowledge_capture_block(force_refresh: bool = False) -> Dict[str, Any]:
    """Return knowledge_capture config with defaults merged."""
    del force_refresh  # reserved for tests
    raw = _load_merged_config().get("knowledge_capture") or {}
    out: Dict[str, Any] = {}
    for key, default_val in _DEFAULTS.items():
        if isinstance(default_val, dict):
            section = dict(default_val)
            override = raw.get(key)
            if isinstance(override, dict):
                section.update(override)
            out[key] = section
        else:
            out[key] = raw.get(key, default_val)
    return out


def artifact_cfg() -> Dict[str, Any]:
    return get_knowledge_capture_block()["artifact_ingestion"]


def research_cfg() -> Dict[str, Any]:
    return get_knowledge_capture_block()["research_capture"]


def synthesis_cfg() -> Dict[str, Any]:
    return get_knowledge_capture_block()["session_synthesis"]


def extraction_llm_cfg() -> Dict[str, Any]:
    return get_knowledge_capture_block()["extraction"]["llm"]


def recall_cfg() -> Dict[str, Any]:
    return get_knowledge_capture_block()["recall"]


def bridge_cfg() -> Dict[str, Any]:
    return get_knowledge_capture_block()["claude_memory_bridge"]


def prompt_remember_cfg() -> Dict[str, Any]:
    return get_knowledge_capture_block()["prompt_remember"]


def default_topic_cluster(project_id: str) -> str:
    return f"knowledge:{project_id}"


def artifact_suffixes() -> List[str]:
    return list(artifact_cfg().get("suffixes") or [".md", ".txt", ".mdx"])


def is_ingestible_artifact_path(path: str) -> bool:
    """True when file path looks like a plan/doc we should learn from."""
    if not path:
        return False
    p = Path(path)
    name_lower = p.name.lower()
    suffixes = [s.lower() for s in artifact_suffixes()]
    if any(name_lower.endswith(s) for s in suffixes):
        return True
    subs = artifact_cfg().get("plan_name_substrings") or []
    return any(sub in name_lower for sub in subs)
