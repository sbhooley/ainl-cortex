# AINL Cortex — Self-healing runtime

Production-grade automatic recovery for install, import, dependency, and backend mismatches.
Users should not need to diagnose `sys.path`, missing wheels, or stale MCP processes.

## Architecture

```text
setup.sh / mcp_launch.sh / SessionStart / every call_tool
        │
        ▼
  runtime_bootstrap.bootstrap_runtime()
        ├── import_compat   — sys.path + bare mcp_server module shims
        ├── deps_compat     — ainativelang pip heal + AINLTools reload
        ├── native_compat   — ainl_native pip heal + config→python fallback
        ├── build_stamp     — git SHA runtime vs disk (stale MCP banner)
        └── operator_checks — plugin enabled, venv, Python version banners
```

## Area checklist (6 long-term fixes)

| # | Area | Status | Implementation |
|---|------|--------|----------------|
| 1 | Bare `mcp_server` imports | **Done** | `import_compat.ensure_mcp_module_shims()` registers all legacy top-level names |
| 2 | Missing `ainativelang` | **Done** | `deps_compat.ensure_ainativelang()` + `call_tool` retry + SessionStart |
| 3 | Native backend / `ainl_native` | **Done** | `native_compat` pip heal; `get_graph_store()` syncs config to `python` on failure |
| 4 | Stale MCP after `git pull` | **Done** | `build_stamp` — `logs/mcp_runtime.json` vs `git HEAD` → SessionStart banner |
| 5 | Hooks ↔ MCP paths | **Done** | `ensure_hooks_path()` in bootstrap (hooks + `shared.*` imports) |
| 6 | Operator-only failures | **Done** | `operator_checks` — clear banner lines (no silent failure) |

## Preflight entrypoints

| Entry | Command / call |
|-------|----------------|
| Setup | `scripts/ensure_runtime_preflight.py` (after venv install) |
| MCP launch | `mcp_launch.sh` → preflight before `exec -m mcp_server.server` |
| Package import | `mcp_server/__init__.py` → `bootstrap_runtime()` |
| MCP server | `server._bootstrap_import_compat()` → full bootstrap |
| Tool dispatch | `call_tool` → `bootstrap_runtime(quick=True)` |
| SessionStart | `verify_mcp_imports` + `operator_checks` + stale MCP line |

## Smoke / verify

- `[0b]` live `memory_store_failure`
- `[0c]` bare `node_types` without `mcp_server/` on PYTHONPATH
- `[0d]` `graph_store` + `retrieval` bare imports
- `[0e]` `ensure_ainativelang` import check (compiler_v2)
- `verify_activation.sh` — runtime preflight + memory_store_failure

## Future (optional)

- Mechanical codemod: replace all bare imports with `from .module import` (delete shims)
- Claude Code API to reconnect MCP without full IDE restart (platform-dependent)
- Auto-run `migrate_python_to_native.sh` when native empty + python DB populated

## Active todos (maintenance)

All six production areas below are implemented on `main`. Optional follow-ups:

- [ ] Codemod: replace bare imports with `from .module import` and shrink `MCP_BARE_MODULES`
- [ ] Claude Code MCP hot-reload API (platform) to avoid full IDE restart after `git pull`
- [ ] Auto-invoke `migrate_python_to_native.sh` when native DB empty and python DB has data

## Related commits

- `2e549d0` — `node_types` import_compat (initial)
- (runtime_bootstrap series) — full six-area self-healing stack
