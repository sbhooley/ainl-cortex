# Changelog

## 0.4.0 — 2026-05-18

### Cost control (production roadmap)

- **Conversation / action-intent gate** — skips recall, goals, failure advisor, and AINL nudges on chat-only turns (`hooks/shared/conversation_detection.py`).
- **Eco productization** — compression metrics in `logs/hook_metrics.jsonl`, cache mode persistence in `logs/cache_state.json`, SessionStart cost line.
- **MCP `cortex_cost_snapshot`** — read-only session/project aggregates.
- **`cost_profile` presets** — `balanced`, `subscription_safe`, `max_learning`.
- **Tool digests** — zero-LLM summaries + blobs; MCP `memory_get_tool_outcome`.
- **AINL promotion** — `ainl_promote_pattern` MCP + orchestration counterfactuals (`baseline_C_analytical`).
- **Recall quality** — `recall_dropped_nodes` metrics; decay/TTL in retrieval ranking.
- **Output compression** — optional episode `task_description` compression on `stop`.
- **ArmaraOS** — daemon eco hint on SessionStart when bridge is up.
- **Project docs** — hash-gated `AGENTS.md` / `CLAUDE.md` semantic nodes.
- **Procedure cards** — high-fitness pattern injection when prompt matches.
- Docs: [`docs/COST_CONTROL.md`](docs/COST_CONTROL.md).
