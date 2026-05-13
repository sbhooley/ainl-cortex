# AINL Plugin Instructions for Claude Code

## Plugin Setup (for new users)

If a user says they just cloned or downloaded this plugin and needs help activating it:

**The one-command install:**
```bash
cd ~/.claude/plugins/ainl-cortex
bash setup.sh
# then restart Claude Code
```

`setup.sh` handles: venv creation, dep install, marketplace registration, settings.json update, and config defaults.

**To verify it worked** after restarting: `/mcp` should list ~20 tools starting with `ainl-cortex__`.

**Common issues:**
- `python3 not found` → install Python 3.10+ from python.org
- `pip install fails` → run `bash setup.sh` again with internet connection
- No banner at startup → check `~/.claude/settings.json` has `"enabledPlugins": {"ainl-cortex@ainl-local": true}`; if missing, re-run setup.sh
- Only ~13 tools (no ainl_ tools) → run `pip install ainativelang[mcp]>=1.7.0` inside `.venv`

**Native Rust backend (optional, higher fidelity):**
Requires armaraos source at `~/.openclaw/workspace/armaraos/` and Rust toolchain 1.75+. setup.sh detects this automatically and sets `store_backend: native` in config.json. The Rust extension (`ainl_native`) builds automatically at the next SessionStart.

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

**Native backend** — wraps armaraos `ainl-memory`, `ainl-trajectory`, `ainl-persona`, `ainl-procedure-learning` crates via `ainl_native.so` (PyO3). Adds: `AinlTrajectoryBuilder`, `cluster_experiences → distill_procedure` pipeline, `AinlPersonaEngine`, `tag_turn`, `check_freshness/can_execute`, `score_reuse`, anchored summary compression.

**Auto-build**: `hooks/startup.py:_ensure_ainl_native()` builds `ainl_native` at every SessionStart using maturin. Falls back silently to Python if build fails. Build command (run manually if needed):
```bash
cd ~/.claude/plugins/ainl-cortex
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
  .venv/bin/maturin develop --release \
  --manifest-path ainl_native/Cargo.toml
```

**Prerequisites for native**: Rust toolchain 1.75+, armaraos source at `~/.openclaw/workspace/armaraos/` (provides ainl-* crates). See README.md § Backend Selection for full details.

**Migrating Python → Native**: `python3 migrate_to_native.py --flip-config` migrates existing data and flips the config in one step.

**Factory**: `mcp_server/graph_store.py:get_graph_store(db_path)` — always use this, never instantiate `SQLiteGraphStore` or `NativeGraphStore` directly. It reads `config.json` and returns the right store with fallback.

**Two DBs** (native mode only):
- `ainl_memory.db` — Python schema (legacy; no longer written after migration)
- `ainl_native.db` — Rust ainl-memory schema (active; single source of truth)

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
