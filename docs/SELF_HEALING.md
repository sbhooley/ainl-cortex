# AINL Cortex — Self-healing runtime

Production-grade automatic recovery for install, import, dependency, and backend mismatches.
Users should not need to diagnose `sys.path`, missing wheels, or stale MCP processes.

## Architecture

```text
setup.sh / mcp_launch.sh / SessionStart / every call_tool
        │
        ▼
  runtime_bootstrap.bootstrap_runtime()
        ├── import_compat   — sys.path + minimal legacy shims (relative imports primary)
        ├── deps_compat     — ainativelang pip heal + AINLTools reload
        ├── native_compat   — ainl_native pip heal + config→python fallback
        ├── migration_compat — auto migrate_python_to_native when native + unmigrated data
        ├── build_stamp     — git SHA runtime vs disk
        ├── mcp_reload      — /reload-plugins nudge after git pull / setup
        └── operator_checks — plugin enabled, venv, Python version banners
```

## Area checklist (6 core + 3 follow-ups)

| # | Area | Status | Implementation |
|---|------|--------|----------------|
| 1 | Bare `mcp_server` imports | **Done** | Relative imports in all `mcp_server/*.py`; `scripts/codemod_relative_imports.py`; minimal shims |
| 2 | Missing `ainativelang` | **Done** | `deps_compat.ensure_ainativelang()` |
| 3 | Native backend / `ainl_native` | **Done** | `native_compat` + `get_graph_store()` fallback |
| 4 | Stale MCP after `git pull` | **Done** | `build_stamp` + `mcp_reload` → **`/reload-plugins`** first |
| 5 | Hooks ↔ MCP paths | **Done** | `ensure_hooks_path()` |
| 5b | Windows `run_hook.cmd` / `hooks.json` | **Done** | `hook_launcher_heal.ensure_hook_launchers()` on MCP start, `run_hook.py`, install, SessionStart banner |
| 6 | Operator-only failures | **Done** | `operator_checks` |
| 6b | Claude install path / MCP launcher / ainativelang | **Done** | `claude_integration_heal.heal_claude_integration()` on SessionStart + MCP bootstrap |
| 7 | Relative-import codemod | **Done** | `scripts/codemod_relative_imports.py` |
| 8 | MCP reload without full restart | **Done** | `mcp_reload.request_mcp_reload()` after pull/setup; SessionStart banner |
| 9 | Auto native migration | **Done** | `migration_compat.scan_and_auto_migrate_all_projects()` on SessionStart when `store_backend=native` |

## MCP reload flow

1. `git pull`, `setup.sh`, or notification auto-update → `request_mcp_reload()` writes `logs/mcp_reload_requested.json`
2. SessionStart → banner: run **`/reload-plugins`** (Claude Code built-in)
3. MCP restart → `write_mcp_runtime_stamp()` clears reload request when new process boots
4. If still stale → full Claude Code quit (platform limit)

There is no public API to SIGKILL the MCP child from a hook; `/reload-plugins` is the supported hot-reload path.

## Auto native migration

When **`memory.store_backend`** is **`native`**, **`ainl_native`** is importable, **`ainl_memory.db`** has data, and **`ainl_native.db`** is empty:

- SessionStart runs **`scripts/migrate_python_to_native.sh`** once per 24h (per `logs/auto_migrate_state.json`)
- Opt out: `"memory": { "auto_migrate_to_native": false }`

## Preflight entrypoints

| Entry | Command / call |
|-------|----------------|
| Setup | `scripts/ensure_runtime_preflight.py` |
| Codemod | `python3 scripts/codemod_relative_imports.py [--check]` |
| MCP launch | `mcp_launch.sh` → preflight |
| SessionStart | `session_start_extras()` — reload nudge + auto-migrate |

## Smoke / verify

- `[0b]`–`[0e]` — import compat + ainativelang
- `scripts/codemod_relative_imports.py --check` — CI gate for bare imports
- `scripts/bug_hunt_matrix.sh` — install / MCP / native upgrade regression matrix

## Native upgrade

- `scripts/claude_do_native_upgrade.sh` — **Claude Code entrypoint** when user asks to install Rust / upgrade native
- `scripts/native_upgrade_status.py --json` — machine-readable: migration vs greenfield vs reload-only
- `scripts/upgrade_to_native.sh` — low-level orchestration (Rust optional → migrate → flip → reload marker)
- `setup.sh --enable-native` / `AINL_CORTEX_ENABLE_NATIVE=1` — run upgrade after install
- Greenfield (no graph data): `setup.sh` on a TTY may auto-enable native when `ainl_native` is ready
- After any backend flip: user must run **`/reload-plugins`** (hooks cannot invoke slash commands)

## Related commits

- `2e549d0` — `node_types` import_compat
- `dad9799` — runtime_bootstrap six-area stack
- (follow-ups) — relative imports, mcp_reload, migration_compat
