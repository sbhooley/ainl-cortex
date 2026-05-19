# Claude Code — native upgrade playbook

When a user asks to **install Rust**, **upgrade to native**, or **migrate memory**, Claude should follow this flow exactly.

## Step 1 — Diagnose (no guessing)

```bash
cd "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/ainl-cortex}"
.venv/bin/python scripts/native_upgrade_status.py --json
```

Read these fields:

| Field | Meaning |
|-------|---------|
| `store_backend` | `python` or `native` |
| `graph_memory_has_data` | Any project has nodes in `ainl_memory.db` |
| `needs_memory_migration` | Python backend + existing data → full migrate |
| `needs_config_flip` | Still on Python → upgrade script flips config |
| `unmigrated_project_hashes` | Native config but Python DB not copied yet |
| `recommended_actions` | Exact commands to run |

## Step 2 — Execute

```bash
bash scripts/claude_do_native_upgrade.sh
```

Dry-run first if unsure:

```bash
bash scripts/claude_do_native_upgrade.sh --dry-run
```

## Step 3 — Reload MCP (user action)

Claude **cannot** run `/reload-plugins`. After a successful upgrade, tell the user:

> Please run **/reload-plugins** in Claude Code (or fully quit and reopen). Then check **/mcp** for ~30 ainl-cortex tools.

## Do not

- Edit `config.json` by hand
- Run `migrate_to_native.py` directly unless debugging a failed migration
- Skip reload after `git pull`, `setup.sh`, or backend changes

## Source of truth

- `mcp_server/native_upgrade_runbook.py` — assessment logic
- `CLAUDE.md` — plugin instructions loaded by Claude Code
