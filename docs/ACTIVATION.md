# AINL Cortex — Activation & Setup Guide

> **Quick answer:** Run `bash setup.sh` then restart Claude Code. That's it.

---

## A Note on Names

**AINL Cortex** is the product name. `ainl-graph-memory` is the internal plugin ID that Claude Code uses for settings, MCP registration, and the plugin directory. These are intentionally different — the ID stays stable so existing installs and settings aren't broken when the product name changes.

| What you see | Value |
|---|---|
| Product name | AINL Cortex |
| Plugin directory | `~/.claude/plugins/ainl-graph-memory/` |
| MCP server ID | `ainl-graph-memory` |
| Settings key | `ainl-graph-memory@ainl-local` |
| MCP tool prefix | `ainl-graph-memory__*` |
| GitHub repo | `https://github.com/sbhooley/ainl-cortex` |

There is no conflict — the directory is named `ainl-graph-memory` on purpose.

---

## Installation

```bash
git clone https://github.com/sbhooley/ainl-cortex.git ~/.claude/plugins/ainl-graph-memory
cd ~/.claude/plugins/ainl-graph-memory
bash setup.sh
```

Then **restart Claude Code**.

`setup.sh` handles everything automatically:
- Creates `.venv` and installs Python dependencies
- Registers the plugin with Claude Code (marketplace + `settings.json`)
- Detects whether the Rust native backend is available and sets the default
- Writes `config.json` with safe defaults

### Native Rust Backend (optional)

If you have the [ArmaraOS](https://github.com/sbhooley/armaraos) source at `~/.openclaw/workspace/armaraos/` and Rust 1.75+, `setup.sh` detects this and sets `store_backend: native` in `config.json`. The Rust extension builds automatically on the next SessionStart. See [README.md § Backend Selection](../README.md) for full details.

---

## Verifying Activation

### 1. SessionStart banner

On every session start you should see:

```
[AINL Cortex]  Plugin root: ~/.claude/plugins/ainl-graph-memory
  • Graph DB: ready (ainl_memory.db)
  • Compression: BALANCED (on)  ~savings ~40–60%
  • MCP stack: OK
  ...
```

If the banner is absent, see [Troubleshooting](#troubleshooting) below.

### 2. MCP tools

Run `/mcp` in Claude Code. You should see **~24 tools** prefixed with `ainl-graph-memory__`:

| Group | Tools |
|---|---|
| Memory (7) | `memory_store_episode`, `memory_store_semantic`, `memory_store_failure`, `memory_promote_pattern`, `memory_recall_context`, `memory_search`, `memory_evolve_persona` |
| Goals (4) | `memory_set_goal`, `memory_update_goal`, `memory_complete_goal`, `memory_list_goals` |
| AINL (6) | `ainl_validate`, `ainl_compile`, `ainl_run`, `ainl_capabilities`, `ainl_security_report`, `ainl_ir_diff` |
| A2A (7) | `a2a_send`, `a2a_list_agents`, `a2a_register_agent`, `a2a_note_to_self`, `a2a_register_monitor`, `a2a_task_send`, `a2a_task_status` |

### 3. Memory databases

After a few interactions:

```bash
ls ~/.claude/projects/*/graph_memory/
# ainl_memory.db  (or ainl_native.db for Rust backend)
```

### 4. Hook activity

```bash
tail -20 ~/.claude/plugins/ainl-graph-memory/logs/hooks.log
```

You should see timestamped entries for `user_prompt_submit`, `post_tool_use`, etc.

---

## What Happens Automatically

### Hook system (7 hooks, zero config required)

| Hook | When | What it does |
|---|---|---|
| `SessionStart` | Session opens | Banner, backend init, `a2a_note_to_self` injection, freshness gating |
| `UserPromptSubmit` | Before each prompt | Context injection, trajectory start, procedure scoring |
| `UserPromptExpansion` | Before each prompt | Semantic compression (40–70% token savings on long prompts) |
| `PostToolUse` | After each tool call | Episode capture, trajectory step, failure detection |
| `PreCompact` | Before context compaction | Flush buffered captures; snapshot anchored summary |
| `PostCompact` | After context compaction | Update anchored summary to post-compact state |
| `Stop` | Session ends | Pattern consolidation, persona finalization, full flush |

### What to expect over time

**First interaction:** Plugin initializes silently — no visible output beyond the banner.

**After 5–10 interactions:**
- Memory databases growing in `~/.claude/projects/*/graph_memory/`
- Persona traits beginning to evolve
- Compression applying to longer prompts

**After 20+ interactions:**
- Pattern recognition active (successful tool sequences promoted)
- Failure prevention surfacing past errors
- Persona traits stable and influencing context injection
- Goals auto-inferred from episode clusters

---

## Troubleshooting

### Banner doesn't appear

```bash
# Check settings.json has the plugin
grep -A3 "ainl-graph-memory" ~/.claude/settings.json

# Re-run setup if missing
cd ~/.claude/plugins/ainl-graph-memory && bash setup.sh
```

### Fewer than 24 MCP tools

```bash
# Check AINL package is installed
.venv/bin/python -c "import ainativelang; print(ainativelang.__version__)"

# If missing
.venv/bin/pip install "ainativelang[mcp]>=1.7.0"
```

Then restart Claude Code.

### No hook activity in logs

```bash
# Ensure hooks are executable
chmod +x hooks/*.py

# Test a hook manually
echo '{"projectId":"test","workingDir":"'$PWD'","prompt":"test"}' | \
  .venv/bin/python hooks/user_prompt_submit.py
```

### Python dependencies missing

```bash
cd ~/.claude/plugins/ainl-graph-memory
.venv/bin/pip install -r requirements.txt
```

### MCP server fails to start

```bash
# Test the server directly
.venv/bin/python -m mcp_server.server

# Check server logs
tail -50 logs/mcp_server.log
```

### Native Rust backend build fails

The plugin falls back to the Python backend silently — Claude Code continues working normally. The SessionStart banner shows:

```
• ainl_native (Rust bindings): build failed: ...   ← fell back to python
```

To force a rebuild manually:
```bash
cd ~/.claude/plugins/ainl-graph-memory
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
  .venv/bin/maturin develop --release \
  --manifest-path ainl_native/Cargo.toml
```

---

## Configuration

The plugin works out-of-the-box. To tune it:

```bash
# View current settings
cat ~/.claude/plugins/ainl-graph-memory/config.json
```

Key options in `config.json`:

```json
{
  "memory": {
    "store_backend": "python"      // or "native" (Rust)
  },
  "compression": {
    "mode": "balanced",            // "balanced" | "aggressive" | "off"
    "enabled": true
  }
}
```

Feature flags (environment variables):
- `AINL_MEMORY_ENABLED` — master switch
- `AINL_PERSONA_EVOLUTION` — persona learning
- `AINL_TAGGER_ENABLED` — semantic tagging
- `AINL_LOG_TRAJECTORY` — trajectory capture

---

## Uninstalling

```bash
rm -rf ~/.claude/plugins/ainl-graph-memory

# Optional: remove project memory databases (deletes all learned memory)
# find ~/.claude/projects -name "graph_memory" -type d -exec rm -rf {} +
```

---

## Further Reading

- [README.md](../README.md) — Full feature overview and architecture
- [docs/AINL_LANGUAGE_GUIDE.md](AINL_LANGUAGE_GUIDE.md) — AINL syntax and adapter reference
- [docs/AINL_CONCEPTS.md](AINL_CONCEPTS.md) — Core graph-memory concepts
- [docs/ADVANCED_COMPRESSION.md](ADVANCED_COMPRESSION.md) — Compression modes and tuning
- [docs/USER_GUIDE_AINL.md](USER_GUIDE_AINL.md) — End-to-end AINL workflow guide

---

**Issues:** https://github.com/sbhooley/ainl-cortex/issues
