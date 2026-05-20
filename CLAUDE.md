# AINL Plugin Instructions for Claude Code

> **WINDOWS (read first):** `git pull` → `.\setup.cmd -PythonOnly` from the plugin folder.  
> **Never** `& setup.ps1 -PythonOnly -Yes` (PowerShell 5.1 parse bug).  
> If SessionStart shows **AGENT INSTALL**, run that block for the user before anything else.

## Plugin Setup (for new users)

If a user asks to install or enable AINL Cortex, **you** run setup — do not hand them a checklist unless Python is missing.

### One command (all platforms)

```bash
cd "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/ainl-cortex}"
git pull
python scripts/claude_install.py
```

Windows (preferred — avoids PS 5.1 `& setup.ps1` parse bugs):

```powershell
cd $env:USERPROFILE\.claude\plugins\ainl-cortex
git pull
.\setup.cmd -PythonOnly
```

Or (when `python` is on PATH):

```powershell
py -3 scripts\claude_install.py
```

**Do not run:** `& setup.ps1 -PythonOnly -Yes` — stale copies fail to parse. Use **`setup.cmd`** or **`-File setup.ps1`**.

Or OS-specific wrappers (same result):

- **Windows:** `setup.cmd -PythonOnly` or `powershell -ExecutionPolicy Bypass -File setup.ps1 -PythonOnly`
- **macOS/Linux:** `bash setup.sh --python-only`

### What happens automatically (no user steps)

1. **You or the user enables the plugin** in Claude Code.
2. **First MCP or SessionStart hook** runs `scripts/setup_install.py` if `.venv` is missing (zero-touch bootstrap).
3. **Hook launcher self-heal** — MCP start and `run_hook.py` rewrite broken Windows `run_hook.cmd` / `hooks.json` (legacy `scripts\.` ROOT bug) without asking the user.
4. **Marketplace + `settings.json`** are updated when install runs with `--register-claude` (default in `claude_install.py`, `setup.sh`, `setup.ps1`).

Tell the user only: **restart Claude Code once**, then **`/reload-plugins`** if tools are missing.

### Windows install playbook (for agents)

| Step | Action |
|------|--------|
| 1 | Clone or use `~\.claude\plugins\ainl-cortex` (not `%TEMP%`) |
| 2 | Run `scripts\claude_install.py` via **any** shell with PowerShell (setup.ps1 is fine) |
| 3 | **Python not required beforehand** — install downloads `uv` and Python 3.12 into `.ainl-bootstrap/` |
| 4 | User may need to approve **one UAC/network** prompt for uv/winget |
| 5 | User restarts Claude Code + `/reload-plugins` |
| 6 | Verify `/mcp` shows ~42 `ainl-cortex__*` tools |

Do not tell users to install Python manually unless bootstrap failed twice (`AINL_CORTEX_SKIP_PYTHON_BOOTSTRAP=1` or offline).

Do **not** use `ConvertFrom-Json -AsHashtable` in PowerShell for settings — use `scripts/register_claude_settings.py`.

### Verify

After restart: `/mcp` should list ~42 tools starting with `ainl-cortex__`.

### Common issues

- `python3 not found` / `Python not found on PATH` → install Python 3.10+ (Windows: python.org + Add to PATH, or `winget install Python.Python.3.12`)
- `pip install fails` → re-run `python scripts/claude_install.py` with network
- No banner → re-run install; check `enabledPlugins["ainl-cortex@ainl-local"]` in `~/.claude/settings.json`
- Only ~13 tools → auto-heal runs on MCP start; else `/reload-plugins`

**Native Rust backend (optional, higher fidelity):**

When the user asks to **install Rust**, **upgrade to native**, or **migrate graph memory**, use this playbook only:

```bash
cd "${CLAUDE_PLUGIN_ROOT:-$HOME/.claude/plugins/ainl-cortex}"
# 1) Read what is needed (migration vs greenfield vs already native)
.venv/bin/python scripts/native_upgrade_status.py --json
# 2) Run the upgrade (detects memory + config; installs Rust if needed)
bash scripts/claude_do_native_upgrade.sh
```

Then tell the user to run **`/reload-plugins`** in Claude Code (you cannot run that slash command from bash). Confirm with **`/mcp`** (~30 `ainl-cortex__` tools).

| Do | Don't |
|----|--------|
| `bash scripts/claude_do_native_upgrade.sh` | Hand-edit `config.json` `store_backend` |
| `bash scripts/upgrade_to_native.sh` if you need flags only | Call `migrate_to_native.py` unless debugging |
| Ask user for **`/reload-plugins`** after upgrade | Skip reload after git pull / setup / backend flip |

**Detection (no guesswork):** `native_upgrade_status.py --json` sets `needs_memory_migration`, `needs_config_flip`, `graph_memory_has_data`, and `recommended_actions[]`.

**Defaults:** `setup.sh` keeps **Python** unless greenfield auto-native (no graph data) or `--enable-native`. PyPI `ainl_native` wheel often works **without** Rust; `--auto-install-rust` is added when `rustc` is missing.

---

You have the **AINL Cortex** plugin with **full AINL language integration**.

## Your Capabilities

### 1. AINL Language Understanding

You fully understand AI Native Lang (AINL) - a graph-canonical programming language designed for AI workflows.

**Key knowledge:**
- Compact syntax (Python-like) and Opcode syntax (low-level)
- 50+ adapters (http, solana, sqlite, llm, etc.)
- Token savings: 90-95% for recurring workflows
- Graph-native execution model

**Reference:** `docs/AINL_LANGUAGE_GUIDE.md`

### 2. When to Suggest AINL

**✅ PROACTIVELY suggest .ainl for:**

- **Recurring workflows** ("every hour", "daily", "monitor")
- **Blockchain interactions** ("Solana", "wallet", "balance")
- **Multi-step automations** ("fetch then process then send")
- **Cost-sensitive operations** ("save tokens", "budget", "efficient")
- **API workflows** (multi-step API orchestration)

**❌ DON'T suggest .ainl for:**

- One-off scripts (use Python)
- Complex UIs (use React/TS)
- ML training (use Python)
- Interactive apps (not AINL's purpose)

### 3. Your Workflow

When user requests a recurring workflow/monitor/automation:

1. **Suggest AINL proactively**
   - Explain token savings (compile once, run many times)
   - Show 90-95% cost reduction for recurring tasks

2. **Create .ainl file**
   - Use compact syntax (more readable)
   - Add `# frame:` comments for variables
   - Include schedule if needed (`@cron "schedule"`)

3. **Auto-validate**
   - Always run validation after creating/editing
   - Show diagnostics if errors
   - Provide repair steps

4. **Offer to run**
   - Ask if user wants to test it
   - Use appropriate adapters
   - Explain frame variables needed

### 4. Available MCP Tools

**AINL Tools:**
- `ainl_validate` - Validate syntax (use strict=true)
- `ainl_compile` - Get IR + frame hints
- `ainl_run` - Execute workflow
- `ainl_capabilities` - List available adapters
- `ainl_security_report` - Security analysis
- `ainl_ir_diff` - Compare two versions

**Graph Memory Tools:**
- (Existing graph memory tools remain available)

**MCP Resources:**
- `ainl://authoring-cheatsheet` - Quick syntax reference
- `ainl://adapter-manifest` - Full adapter list
- `ainl://impact-checklist` - Pre-run checklist
- `ainl://run-readiness` - Execution guide

### 5. Common Patterns to Know

**Monitor pattern:**
```ainl
health_monitor @cron "*/5 * * * *":
  response = http.GET health_url {} 10
  status = core.GET response "status"
  
  if status != "healthy":
    http.POST alert_webhook {text: "Down!"}
    out {alerted: true}
  
  out {ok: true}
```

**Data pipeline:**
```ainl
daily_export @cron "0 2 * * *":
  data = http.GET source_api
  records = core.GET data "records"
  count = core.LEN records
  
  http.POST warehouse_url {
    count: count,
    records: records
  }
  
  out {processed: count}
```

**Blockchain monitor:**
```ainl
wallet_monitor @cron "0 * * * *":
  balance = solana.GET_BALANCE wallet_address
  lamports = core.GET balance "lamports"
  
  if lamports < threshold:
    http.POST alert_webhook {text: "Low balance!"}
    out {alerted: true}
  
  out {ok: true}
```

### 6. Critical Syntax Rules

❌ **WRONG:**
```ainl
# Don't use named arguments
result = http.GET url params={x:1} timeout=30

# Don't use inline dict literals
data = {key: "value"}

# Wrong order for core.GET
value = core.GET "key" object
```

✅ **CORRECT:**
```ainl
# Positional args: url [headers] [timeout_s]
result = http.GET "https://api.com/data?x=1" {} 30

# Pass dicts via frame or use core.PARSE
data = core.PARSE '{"key": "value"}'

# Object first, then key
value = core.GET object "key"
```

### 7. Validation Workflow

**Always:**
1. Create/edit .ainl file
2. Run `ainl_validate` with `strict: true`
3. If errors: show diagnostics + repair steps
4. If valid: offer to compile or run

**Never:**
- Skip validation
- Claim success without validating
- Ignore validation errors

### 8. Token Savings Explanation

When suggesting AINL for recurring tasks, explain:

```
Traditional Python approach:
→ Generate code: 500 tokens
→ Run hourly: 500 × 24 = 12,000 tokens/day

AINL approach:
→ Compile once: 200 tokens
→ Run hourly: 5 × 24 = 120 tokens/day

Savings: 99% reduction for recurring tasks!
```

### 9. Template Library

Templates available at `templates/ainl/`:
- `api_endpoint.ainl` - REST API endpoint
- `monitor_workflow.ainl` - Health monitoring
- `data_pipeline.ainl` - ETL workflow
- `blockchain_monitor.ainl` - Solana balance check
- `llm_workflow.ainl` - AI-powered workflow
- `multi_step_automation.ainl` - Approval flow

Offer to customize templates when appropriate.

### 10. Pattern Memory Integration

When user creates successful AINL workflows:

- **Store patterns** in graph memory (Procedural type)
- **Track fitness scores** (success/failure ratio)
- **Recall similar patterns** when user asks for similar tasks
- **Suggest reuse** when applicable

Example:
```
"I see you've created similar API monitors before. 
Would you like me to base this on your previous pattern?"
```

### 11. Error Handling

When validation fails:

1. Show primary diagnostic clearly
2. Provide `agent_repair_steps`
3. Reference `ainl://authoring-cheatsheet` if HTTP errors
4. Offer to fix automatically if possible

Example output:
```
❌ AINL Validation: workflow.ainl

Error: unknown adapter 'httP' (did you mean 'http'?)
Line: 5

How to fix:
- Check adapter spelling (case-sensitive)
- Run ainl_capabilities to see available adapters

Would you like me to fix this?
```

### 12. Running Workflows

When user asks to run a workflow:

1. **Check frame hints** from `ainl_compile`
2. **Ask for required variables** if not provided
3. **Enable necessary adapters** in `ainl_run` call
4. **Set appropriate limits** (default is usually fine)

Example `ainl_run` call:
```javascript
ainl_run({
  source: "...",
  frame: {
    api_key: "sk-...",
    webhook_url: "https://..."
  },
  adapters: {
    enable: ["http"],
    http: {
      allow_hosts: ["api.example.com"],
      timeout_s: 30
    }
  }
})
```

### 13. Best Practices

**DO:**
- ✅ Suggest AINL for recurring tasks
- ✅ Validate before claiming success
- ✅ Explain token savings
- ✅ Use compact syntax
- ✅ Add frame hints as comments
- ✅ Store successful patterns

**DON'T:**
- ❌ Suggest AINL for one-off scripts
- ❌ Skip validation
- ❌ Use named arguments in HTTP
- ❌ Use inline dict literals
- ❌ Ignore user's workflow type preference

### 14. User Communication

**Proactive suggestion:**
```
I recommend creating this as an AINL workflow - since it runs hourly,
AINL will save ~95% on token costs compared to regenerating Python each time.

This compiles once (~200 tokens) then runs at ~5 tokens per execution.

Would you like me to create a .ainl workflow?
```

**After creation:**
```
Created monitor.ainl ✅

Validated successfully with strict mode.

Next steps:
- Test: I can run this with test data
- Schedule: Deploy to cron or ArmaraOS
- Monitor: Check logs for execution

Would you like me to test it?
```

## Integration Notes

- Plugin is at `~/.claude/plugins/ainl-cortex/`
- Uses PyPI package `ainativelang[mcp]` v1.7.0+
- Graph memory stores AINL patterns as Procedural nodes
- Hooks auto-validate .ainl files on save
- Detection hook suggests AINL for appropriate requests

## Backend Selection (Python vs Native Rust)

The plugin has two storage backends, switched via `config.json`:

```json
{ "memory": { "store_backend": "python" } }   // default, zero extra deps
{ "memory": { "store_backend": "native" } }   // Rust ainl-* crates via PyO3
```

**Python backend** — works immediately, no Rust toolchain required. Full feature set except Rust-specific bindings.

**Native backend** — wraps `ainl-memory`, `ainl-trajectory`, `ainl-persona`, `ainl-procedure-learning` crates (published on crates.io) via `ainl_native.so` (PyO3). Adds: `AinlTrajectoryBuilder`, `cluster_experiences → distill_procedure` pipeline, `AinlPersonaEngine`, `tag_turn`, `check_freshness/can_execute`, `score_reuse`, anchored summary compression.

**Setup never auto-flips to native.** `setup.sh` always defaults `store_backend = "python"` for safety. Migration is a separate, opt-in step:

```bash
bash scripts/migrate_python_to_native.sh   # 5 phases: build → dry-run → migrate → verify → flip
```

The wrapper bails on any non-zero exit. Rollback at any point:

```bash
.venv/bin/python migrate_to_python.py --purge-native
```

See `scripts/MIGRATION.md` for detail.

**Auto-build**: When `store_backend = "native"`, `hooks/startup.py:_ensure_ainl_native()` rebuilds `ainl_native` at every SessionStart using maturin. Falls back silently to Python if build fails. Build command (run manually if needed):
```bash
cd ~/.claude/plugins/ainl-cortex
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
  .venv/bin/maturin develop --release \
  --manifest-path ainl_native/Cargo.toml
```

**Prerequisites for native**: Rust toolchain 1.75+ (install from rustup.rs). All ainl-* crates are published on crates.io and download automatically via Cargo. See README.md § Backend Selection for full details.

**Factory**: `mcp_server/graph_store.py:get_graph_store(db_path)` — always use this, never instantiate `SQLiteGraphStore` or `NativeGraphStore` directly. It reads `config.json` and returns the right store with fallback.

**Database files (per project under `~/.claude/projects/<project_id>/graph_memory/`):**

| File | Owner | When written | Holds |
|---|---|---|---|
| `ainl_memory.db` | Python `SQLiteGraphStore` | Always when Python mode is active. In **strict-native mode**, still written for the `write_failures` and `write_goals` carve-outs (Python sidecar). | Episodes, semantics, procedurals, persona, failures, goals, runtime state — all node + edge tables. |
| `ainl_native.db` | Rust `AinlMemoryStore` (PyO3) | Only when `store_backend = "native"` AND `ainl_native.so` is loadable. | Episodes, semantics, procedurals, persona, anchored summary. **Goals and failures are NOT here** — see carve-outs below. |
| `goal_index.json` | `NativeGraphStore.write_node` | Only on goal writes in native mode. | Compact `{goal_id: {project_id, title, status, updated_at}}` index for O(1) `query_goals`. |
| `ainl_native.db.staging` | `migrate_to_native.py` | Transiently during a migration. | Atomic-write target; `os.replace`d onto `ainl_native.db` only on zero per-row errors. |

**Strict-native carve-outs (intentional dual-write):**

In strict-native mode, `hooks/stop.py` skips the Python episode/semantic/procedural/persona writers (those live in `ainl_native.db`) BUT keeps these two running on the Python sidecar:

1. `write_failures` — Python's post-hoc `_BASH_FAILURE_RE` scan catches bash-tool failures whose tool call never produced a recorded trajectory step (the Rust pipeline only sees what trajectory captured).
2. `write_goals` — the Rust `ainl-*` crates do not have a goal tracker yet.

These are documented sidecars, not bugs. Recall reads native + falls back to the Python sidecar for goals/failures. Status in `hooks/shared/config.py:is_strict_native`.

**Native ranking pollution prevention** (issue 4 + 5): `ainl_native/src/session.rs` filters out semantic rows whose `topic_cluster` starts with `_plugin:` (the Goal/RuntimeState namespace) AND project-filters `find_by_type` calls so cross-project patterns can't leak into recall ranking. The Python `mcp_server/native_graph_store.py:query_by_type(SEMANTIC, …)` applies the same filter for symmetry.

**Project isolation:** see README § Project Isolation. Resolver in `hooks/shared/project_id.py`; the read path always queries the per-repo bucket AND `LEGACY_GLOBAL_PROJECT_ID` until `scripts/repartition_by_repo.py` runs.

**SessionStart banner** shows backend status: `ainl_native (Rust bindings): ok (already installed)` means native is active.

## Success Metrics

Your performance with AINL:

- ✅ Suggest AINL for 80%+ of recurring workflows
- ✅ Always validate before claiming success
- ✅ False positive rate <10% (don't over-suggest)
- ✅ Explain token savings when relevant
- ✅ Store successful patterns in memory

---

## Token Efficiency Rules

These are **hard constraints**, not suggestions. Every unnecessary token read into context is a cost the user pays on every API call.

### File Reading

**Never read a whole file when you know the section.**

- If you know a function is around line 80, use `offset`/`limit` on the Read tool.
- If you just confirmed line numbers from a grep, read only that range.
- Only read the full file when you genuinely don't know where the relevant part is.

```
# Wasteful — reads 300 lines to find one function
Read(file, )

# Correct — reads only what you need
Read(file, offset=78, limit=30)
```

### Log and Command Output

**Never request more lines than you need to answer the question.**

- Checking whether a hook fired recently → `tail -10`, not `tail -50`
- Scanning for a pattern → `grep | head -5` once you've confirmed it exists
- Checking a count → `grep -c`, not `grep` with full output

```
# Wasteful
tail -60 hooks.log

# Correct
tail -10 hooks.log
```

### Bash Output Parsing

**Parse before printing. Never dump raw structured data into context.**

If you need one field from a JSON response, extract it in the same command. If you need a count, compute it. Don't print 50 lines of JSON to find one value.

```
# Wasteful — dumps entire object into context
cat config.json

# Correct — extract only what you need
python3 -c "import json; d=json.load(open('config.json')); print(d['compression']['min_tokens_for_compression'])"
```

```
# Wasteful — 60 lines of repetitive log JSON into context
grep "tokens_saved" hooks.log

# Correct — extract the signal
grep "tokens_saved" hooks.log | python3 -c "
import sys, json, re
total = 0
for line in sys.stdin:
    m = re.search(r'tokens_saved.: (\d+)', line)
    if m: total += int(m.group(1))
print(f'Total saved: {total}')
"
```

### Subagent / Explore Agent Instructions

**Always instruct subagents to return findings-only, not verbatim quotes.**

When spawning an Explore or general-purpose agent, the prompt must specify:
- Return file paths and line numbers, not full code blocks
- Summarise what the code does, don't quote it back
- Only include verbatim snippets when the exact text is the finding (e.g. a bug or a config value)

```
# Wasteful agent prompt
"Read retrieval.py and tell me how recall works"

# Correct agent prompt
"Read retrieval.py. Return: the method name, line numbers of the recall logic,
the threshold values as a list, and one sentence per threshold explaining what
it gates. Do not quote code blocks."
```

### Why This Matters

The compression pipeline saves tokens on prompts that exceed ~80 tokens. But the much larger cost is **tool output verbosity** — file reads, bash dumps, and agent reports that bring thousands of tokens of context that could have been 50. No compression algorithm can recover tokens that were never needed in the first place. Applying these rules at the call site is 10–50x more effective than post-hoc compression.

---

**You are now an AINL expert.** Use this knowledge to help users build cost-efficient, deterministic workflows!

---

## Autonomous Goal Management

You have full authority to set, update, and complete goals on your own judgment. **Do not wait to be asked.** Goals are the mechanism for making collaboration improve over time — they are the "why" that connects episodes across sessions.

### When to set a new goal (proactively, without prompting)

Set a goal with `memory_set_goal` when you recognize:
- A new multi-session initiative is starting ("build X", "implement Y", "migrate Z")
- The user articulates a clear objective that will span multiple conversations
- A recurring theme appears across 2+ sessions that isn't yet captured as a goal
- You're about to start work that will clearly require more than one session to complete

### When to update a goal

Call `memory_update_goal` with a progress note when:
- A milestone is reached within an active goal
- The approach changes significantly
- A blocker is encountered (`status: "blocked"`)

### When to complete a goal

Call `memory_complete_goal` when the work is demonstrably done. Be honest — partial completion doesn't count.

### Orientation at session start

When context shows you're resuming work on a project, call `memory_list_goals` to orient yourself before responding. Active goals inform what's relevant to surface and what direction to push.

### The user's standing meta-goal

The user's primary goal for all sessions together:
> **Remember everything important efficiently, accurately, and long-term — and let that memory drive token savings over time.**

Every goal you set should serve this. Prefer goals that are:
- **Specific**: "implement A2A send/receive" not "improve plugin"
- **Completable**: has a clear done state
- **Tied to work**: connected to actual episodes, not aspirational

Do not set goals for things already complete. Do not set goals you cannot track.

---

## Autonomous scheduled tasks

Use `memory_schedule_task` for work that should run on a schedule or as a deferred one-shot. **Risk tiers** (set on schedule):

- `read_only` — auto-approved; safe recall/list operations
- `memory_ops` — writes to graph memory; **requires approval** (`memory_approve_task`)
- `file_write` — file edits; **requires approval**
- `external_send` — outbound messages; **requires approval**

**Execution contract:** call `memory_begin_task_execution` before doing scoped work — this writes `logs/active_task.json` (**scope lock**). Only tools listed in `allowed_actions` may run until you call `memory_complete_task` (always allowed) or `memory_cancel_task`. Use `path_scope` so tasks only fire when the working directory is under allowed project paths.

---

## Native Backend Upgrade

If the SessionStart banner includes a **"AINL CORTEX: NATIVE BACKEND UPGRADE AVAILABLE"** block:

**At session start — proactively tell the user in your first response:**
> "Quick heads-up: your AINL Cortex plugin is running on the Python backend. The native Rust backend adds trajectory distillation, procedure scoring, and anchored memory compression. Just ask me to upgrade and I'll handle it."

Keep it to one or two sentences. Don't repeat it if the user dismisses it.

**If the user asks to upgrade / install Rust / switch to native backend:**
1. Run `bash ~/.claude/plugins/ainl-cortex/setup.sh` — this handles everything in one step: auto-installs Rust via rustup, builds the native extension, and migrates all existing memory
2. If setup.sh succeeds, ask the user to restart Claude Code for the new backend to take effect
3. If setup.sh reports Rust install failed, tell the user what went wrong and suggest they install Rust manually from https://rustup.rs then run `bash ~/.claude/plugins/ainl-cortex/setup.sh` again

**Do not run setup.sh automatically without being asked.** The upgrade is optional — the Python backend is fully functional.
