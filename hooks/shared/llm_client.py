"""
Optional LLM client for knowledge extraction (stdlib urllib only).
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import List, Optional

logger = logging.getLogger(__name__)


def _load_llm_cfg() -> dict:
    try:
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent.parent
        mcp = str(root / "mcp_server")
        if mcp not in sys.path:
            sys.path.insert(0, mcp)
        from knowledge_config import extraction_llm_cfg

        return extraction_llm_cfg()
    except Exception:
        return {}


def _api_key(cfg: dict) -> Optional[str]:
    env_name = str(cfg.get("api_key_env") or "OPENROUTER_API_KEY")
    key = os.environ.get(env_name, "").strip()
    return key or None


def complete_json_facts(text: str, *, context: str, max_facts: int) -> Optional[List[str]]:
    """
    Ask the configured provider for a JSON array of short durable facts.
    Returns None on any failure (caller falls back to heuristic).
    """
    cfg = _load_llm_cfg()
    if not cfg.get("enabled"):
        return None
    api_key = _api_key(cfg)
    if not api_key:
        return None

    provider = str(cfg.get("provider") or "openrouter").lower()
    model = str(cfg.get("model") or "anthropic/claude-3.5-haiku")
    timeout = float(cfg.get("timeout_s", 25))

    system = (
        "Extract durable factual statements from the user content. "
        "Return ONLY a JSON array of strings (5-20 items). Each string is one "
        "self-contained fact under 400 characters. No markdown, no commentary."
    )
    user = (
        f"Context: {context}\n\n"
        f"Content:\n{text[: int(cfg.get('max_input_chars', 24000))]}\n\n"
        f"Return at most {max_facts} facts as JSON array."
    )

    if provider == "anthropic":
        return _anthropic_facts(api_key, model, system, user, timeout, max_facts)
    return _openrouter_facts(api_key, model, system, user, timeout, max_facts)


def _parse_facts_json(body: str, max_facts: int) -> Optional[List[str]]:
    body = body.strip()
    # Strip markdown fences if present
    if body.startswith("```"):
        body = re.sub(r"^```(?:json)?\s*", "", body)
        body = re.sub(r"\s*```$", "", body)
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        m = re.search(r"\[[\s\S]*\]", body)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, list):
        return None
    facts = []
    for item in data:
        if isinstance(item, str) and len(item.strip()) >= 12:
            facts.append(item.strip())
        if len(facts) >= max_facts:
            break
    return facts or None


def _openrouter_facts(
    api_key: str,
    model: str,
    system: str,
    user: str,
    timeout: float,
    max_facts: int,
) -> Optional[List[str]]:
    url = "https://openrouter.ai/api/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": 2048,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        return _parse_facts_json(content, max_facts)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as e:
        logger.debug("OpenRouter LLM error: %s", e)
        return None


def _anthropic_facts(
    api_key: str,
    model: str,
    system: str,
    user: str,
    timeout: float,
    max_facts: int,
) -> Optional[List[str]]:
    url = "https://api.anthropic.com/v1/messages"
    payload = {
        "model": model,
        "max_tokens": 2048,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        blocks = data.get("content") or []
        text = ""
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "text":
                text += b.get("text", "")
        return _parse_facts_json(text, max_facts)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as e:
        logger.debug("Anthropic LLM error: %s", e)
        return None
