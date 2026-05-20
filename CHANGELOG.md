# Changelog

## 0.4.0 — 2026-05-18

### Windows hook fix + cross-OS self-heal

- **`run_hook.cmd`** — fixed plugin root resolution (`scripts\.` → real root). Restores SessionStart `[AINL Cortex]` banner and stops `scripts\.\scripts\bootstrap_no_python.ps1` PostToolUse errors.
- **`mcp_server/hook_launcher_heal.py`** — auto-repairs broken `run_hook.cmd` and stale `hooks.json` on MCP start, `run_hook.py`, install, and runtime bootstrap (no manual `git pull` required once MCP runs).
- **`scripts/verify_sessionstart.cmd`** — run outside Claude to confirm the hook emits JSON with `[AINL Cortex]`.

### Windows zero-touch install (self-healing)

- **SessionStart AGENT INSTALL banner** — when `.venv`/MCP/setup is incomplete, Claude sees `git pull` + `setup.cmd` (and “do not `& setup.ps1`”) at the top of every session.
- **plugin.json + CLAUDE.md** — Windows install commands in description and first-line agent instructions.
- **Auto-install on first use** — missing `.venv` triggers `setup_install.py` from MCP (`mcp_launch.py`) and hooks (`run_hook.cmd` / `run_hook.py`).
- **Python bootstrap** — downloads **uv** + Python 3.12 when no system Python (`python_bootstrap.py`, `bootstrap_no_python.ps1`).
- **MCP on Windows** — `mcp_launch.cmd` + install-time `plugin.json` patch (`mcp_launcher_config.py`).
- **Marketplace/settings** — `configure_marketplace.py`, `register_claude_settings.py`, `scripts/claude_install.py` for agents.
- **setup.ps1** — PowerShell 5.1 parse fix (no `$Yes` param); uv fallback; `-Yes` alias → `-NonInteractive`.
- **CI** — `windows-install-ci.yml` parses all `.ps1` under PS 5.1 and pwsh.

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
