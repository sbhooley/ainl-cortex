# AINL Cortex — Activation & Setup Guide

> **Quick answer:** Run `bash setup.sh` then restart Claude Code. That's it.

---

## Quick Reference

| What | Value |
|---|---|
| Plugin directory | `~/.claude/plugins/ainl-cortex/` |
| MCP server ID | `ainl-cortex` |
| Settings key | `ainl-cortex@ainl-local` |
| MCP tool prefix | `ainl-cortex__*` |
| GitHub repo | `https://github.com/sbhooley/ainl-cortex` |

---

## Installation

```bash
git clone https://github.com/sbhooley/ainl-cortex.git ~/.claude/plugins/ainl-cortex
cd ~/.claude/plugins/ainl-cortex
bash setup.sh
```

Then **restart Claude Code** (or run `/reload-plugins` once after the first session).

**New users:** If you only enable the plugin from the marketplace without running `setup.sh`, the plugin **auto-installs on first SessionStart or MCP launch** (venv + `ainativelang` + Claude settings wiring). You should see an **AUTO-HEAL** block if anything was repaired; run `/reload-plugins` when prompted.

`setup.sh` handles everything automatically:
- Creates `.venv` and installs Python dependencies
- Registers the plugin with Claude Code (marketplace + `settings.json`)
- Detects whether the Rust native backend is available and sets the default
- Writes `config.json` with safe defaults

### Native Rust Backend (optional)

If you have the [ArmaraOS](https://ainativelang.com/armaraos) source cloned to `~/.armaraos/src/armaraos` and Rust 1.75+, `setup.sh` detects this and sets `store_backend: native` in `config.json`. The Rust extension builds automatically on the next SessionStart. See [README.md § Backend Selection](../README.md) for full details.

---

## Verifying Activation

### SessionStart banner missing after `git clone` / reinstall

Claude Code loads the plugin from **`~/.claude/plugins/installed_plugins.json`**, not only the marketplace symlink. If `installPath` still points at an old **`plugins/cache/ainl-local/ainl-cortex/0.2.0`** directory (deleted or stale), hooks never run from your new tree.

Fix:

```bash
cd ~/.claude/plugins/ainl-cortex
python3 scripts/sync_installed_plugins.py
python3 scripts/configure_marketplace.py
```

Then quit Claude Code, reopen, **`/clear`** or a new session, and **`/reload-plugins`**.

Confirm: `logs/sessionstart_last.json` updates its timestamp after a new session.

**PyPI vs import name:** macOS/Linux install runs `pip install -r requirements-ainl.txt`, which installs **`ainativelang[mcp]>=1.8.0`**. The Python import is **`compiler_v2`**, not `import ainativelang`. A false “not installed” warning usually means something checked the wrong module name, or stderr from an early import before the venv re-exec — not a missing package. Verify with:

```bash
cd ~/.claude/plugins/ainl-cortex
.venv/bin/python3 -c "import compiler_v2; import importlib.metadata as m; print(m.version('ainativelang'))"
```

**Claude Code 2.1.139+:** SessionStart no longer shows `systemMessage` in the chat UI (MCP can still show **connected** in `/mcp`). The plugin is active when `logs/sessionstart_last.json` updates on a new session.

| What you should see | Where |
|---|---|
| Full banner (optional) | Terminal stderr: `SessionStart:startup says:` — set `AINL_CORTEX_SESSIONSTART_STDERR=0` to disable |
| macOS notification | Desktop ping from `terminalSequence` — set `AINL_CORTEX_SESSIONSTART_NOTIFY=0` to disable |
| **First message in session** | Transcript block starting with `━━━ [AINL Cortex] … ━━━` on your **first prompt** after `/clear` or a new session |

If MCP is connected but you see no startup line, send any prompt once — the banner is replayed on first `UserPromptSubmit`.

### 1. SessionStart banner

On every session start you should see (terminal stderr on CC 2.1.139+, or the legacy UI line on older builds):

```
[AINL Cortex]  Plugin root: ~/.claude/plugins/ainl-cortex
  • Graph DB: ready (ainl_memory.db)
  • Compression: BALANCED
    compresses: graph-memory recall brief; long user prompts
    not: SQLite graph store; MCP tools; chat transcript
    benchmark ~40–60% on recall text (varies)
  • MCP stack: OK
  ...
```

If the banner is absent, see [Troubleshooting](#troubleshooting) below.

### 2. MCP tools

Run `/mcp` in Claude Code. You should see **~24 tools** prefixed with `ainl-cortex__`:

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
tail -20 ~/.claude/plugins/ainl-cortex/logs/hooks.log
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
| `Stop` | Session ends | Pattern consolidation, persona finalization, full flush, **content knowledge capture** |

### Content knowledge capture (v0.5.0+)

By default the plugin learns **what** you researched and wrote—not only which files were touched:

- **Artifact ingestion:** `.md` / plan files written or edited in a session are chunked into semantic facts at session end (`knowledge:<project_id>` topic cluster).
- **Research capture:** `web_search` / `web_fetch` results (lower digest threshold) become `research`-tagged facts.
- **Session synthesis:** Sessions that used web + write tools get 5–15 durable summary facts.
- **Recall:** Prompts about prior research, game plans, or “do you remember…” inject topical FTS hits from the graph.
- **“Remember this” in chat:** Saying `remember this`, `save to graph memory`, or similar on a prompt auto-ingests the **last assistant reply** (from Claude’s `transcript_path`), any pasted text, and recent tool digests—no `memory_store_semantic` MCP call required. If the prior reply was too short, you’ll get a hint to paste content and ask again.
- **Optional LLM extraction:** Set `knowledge_capture.extraction.llm.enabled` to `true` and export `OPENROUTER_API_KEY` (or Anthropic) for higher-quality facts; heuristic mode works offline with no key.
- **Optional Claude memory bridge:** Set `knowledge_capture.claude_memory_bridge.enabled` to `true` to mirror `reference_*.md` into the graph.

Backfill existing docs:

```bash
python ~/.claude/plugins/ainl-cortex/scripts/backfill_knowledge.py \
  --project-id YOUR_PROJECT_ID --dry-run
python ~/.claude/plugins/ainl-cortex/scripts/backfill_knowledge.py \
  --project-id YOUR_PROJECT_ID --include-reference-memory
```

Config block: `knowledge_capture` in `config.json` (override via `config.local.json`).

**macOS + Windows:** Paths use `pathlib` + UTF-8 I/O; Claude project folders encode cwd as `-Users-…` (Unix) or `-C-Users-…` (Windows). Transcript JSONL may use CRLF line endings. Run battle tests: `pytest tests/test_knowledge_capture_xplat.py tests/test_*knowledge* tests/test_*remember* tests/test_transcript_tail.py -q`.

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
grep -A3 "ainl-cortex" ~/.claude/settings.json

# Re-run setup if missing
cd ~/.claude/plugins/ainl-cortex && bash setup.sh
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
cd ~/.claude/plugins/ainl-cortex
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
cd ~/.claude/plugins/ainl-cortex
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
  .venv/bin/maturin develop --release \
  --manifest-path ainl_native/Cargo.toml
```

---

## Configuration

The plugin works out-of-the-box. To tune it:

```bash
# View current settings
cat ~/.claude/plugins/ainl-cortex/config.json
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
rm -rf ~/.claude/plugins/ainl-cortex

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
