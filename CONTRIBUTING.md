# Contributing to AINL Cortex

Thanks for helping improve AINL Cortex.

## Where things live

| Area | Entry point |
|------|-------------|
| MCP server & tools | `mcp_server/server.py`, `mcp_server/ainl_tools.py` |
| Hook system | `hooks/startup.py`, `hooks/notifications.py`, `hooks/shared/` |
| Memory & learning | `mcp_server/graph_store.py`, `mcp_server/persona_evolution.py`, `mcp_server/failure_learning.py` |
| Compression | `mcp_server/compression_profiles.py`, `cli/compression_cli.py` |
| Native Rust extension | `ainl_native/` (PyO3 bindings wrapping armaraos crates) |
| CLI tools | `cli/memory_cli.py`, `cli/compression_cli.py`, `cli/trajectory_cli.py` |
| Tests | `tests/` |
| Docs | `docs/` |
| AINL templates | `templates/ainl/` |

## Running tests

```bash
cd ~/.claude/plugins/ainl-cortex
pip install -e ".[dev]"
pytest tests/ -v
```

Run a specific module:

```bash
pytest tests/test_persona_evolution.py -v
pytest tests/test_failure_learning.py -v
pytest tests/test_notifications_feed.py -v
```

Run with coverage:

```bash
pytest tests/ --cov=mcp_server --cov=hooks --cov-report=html
open htmlcov/index.html
```

## Backend selection

The plugin has two storage backends. Tests run against the Python backend by default. To test the native Rust backend, set `store_backend: native` in `config.json` and ensure `ainl_native` has been built:

```bash
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
  .venv/bin/maturin develop --release \
  --manifest-path ainl_native/Cargo.toml
```

The native backend requires Rust 1.75+ and the armaraos source at `~/.armaraos/src/armaraos`. It is optional; the plugin falls back to Python automatically if the build fails.

## Graph store factory

Always use `mcp_server/graph_store.py:get_graph_store(db_path)` to obtain a store instance. Never instantiate `SQLiteGraphStore` or `NativeGraphStore` directly — the factory reads `config.json` and applies the correct backend with fallback.

## Hook system

Hooks fire via Claude Code's hook mechanism. They must be fast and must never raise unhandled exceptions — failures are logged and silently skipped so Claude Code continues working. If you add a new hook, follow the pattern in `hooks/shared/logger.py` for error handling.

## Adding an MCP tool

1. Implement the tool function in the appropriate `mcp_server/` module.
2. Register it in `mcp_server/server.py` (tool list and handler dispatch).
3. Add a test in `tests/`.
4. Document the tool in the README's MCP tools table.

## Docs contracts

If you change behavior described in `docs/`, update the relevant doc. If you add a new feature, add it to:
- The appropriate section of `README.md`
- The `### What activates automatically` list if it fires by default
- The Roadmap if it closes a planned item

## Contributor visibility

Commit attribution on GitHub is the source of truth for who landed changes. Use your GitHub-linked identity for commits you want counted publicly.

## Pull request checklist

- [ ] Tests pass (`pytest tests/ -v`)
- [ ] New behavior is documented in README or docs/
- [ ] No secrets, API keys, or personal paths committed
- [ ] Hook changes are non-fatal on error
- [ ] MCP tool changes update the tool count in README if it changed
