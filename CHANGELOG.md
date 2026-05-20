# Changelog

## 0.4.5 — 2026-05-19

### Windows: auto-update on reload (marketplace cache → live git)

- **`plugin_self_update.py`** — on SessionStart/MCP bootstrap: `git pull` on the live install, clone `%USERPROFILE%\.claude\plugins\ainl-cortex` when only a marketplace **cache** copy exists, repoint `installed_plugins.json`, then nudge `/reload-plugins`.
- **Version mismatch detection** — `installed_plugins.json` `version` vs on-disk `plugin.json`.

## 0.4.4 — 2026-05-19

### SessionStart banner shows plugin version

- First banner line is now `[AINL Cortex vX.Y.Z]` (stderr mirror, systemMessage, first-prompt transcript).

## 0.4.3 — 2026-05-19

### Fix scripts package imports for self-heal

- **`scripts/__init__.py`** — enables `from scripts.sync_installed_plugins` (and marketplace/settings helpers) from MCP and hooks.

## 0.4.2 — 2026-05-19

### Fix scripts import path for self-heal and registration

- **`ensure_scripts_importable()`** — adds plugin root to `sys.path` before `scripts.configure_marketplace` / `sync_installed_plugins` imports from MCP and hooks (fixes fresh-install registration and AUTO-HEAL sync failures).

## 0.4.1 — 2026-05-19

### Self-healing Claude integration (new-user safe)

- **`claude_integration_heal.py`** — auto-fixes stale `installed_plugins.json` cache paths, missing marketplace/settings registration, wrong MCP launcher (`python` → `python3`), and missing `ainativelang` in venv on SessionStart, MCP launch, and hook bootstrap.
- **`canonical_plugin_root()`** — prefers live `~/.claude/plugins/ainl-cortex` over stale `plugins/cache/…` copies when both exist.
- **SessionStart visibility** — stderr mirror on all platforms; first-prompt transcript banner via `sessionstart_visibility.py` (Claude Code 2.1.139+ hides hook UI).
- **ainativelang health** — checks `import compiler_v2` (pip package `ainativelang`); removes false “not installed” warnings.
- **Docs** — `ACTIVATION.md`, `SELF_HEALING.md` updated for zero-touch new-user flow.

## 0.4.0 — 2026-05-18

### Windows SessionStart visibility + timeout

- **SessionStart timeout** raised to **60s** (was 20s; MCP subprocess preflight could exceed it on Windows ARM).
- **In-process MCP verify** on SessionStart (avoids extra 30s subprocess when the hook already runs in `.venv`).
- **Windows terminal mirror** — full `[AINL Cortex]` banner printed to stderr as `SessionStart:startup says:` (native Claude often hides hook UI).
- **`logs/sessionstart_last.json`** — written every SessionStart for offline diagnosis.

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
