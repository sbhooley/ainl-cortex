# AINL Plugin Instructions for Claude Code

## Plugin Setup (for new users)

```bash
cd ~/.claude/plugins/ainl-cortex && bash setup.sh
# then restart Claude Code
```

After restart: `/mcp` should list ~30 tools starting with `ainl-cortex__`.
Native Rust backend is opt-in: `bash scripts/migrate_python_to_native.sh` after setup.

---

You have the **AINL Cortex** plugin with full AINL language integration and graph memory.

## When to Suggest AINL

**✅ Proactively suggest .ainl for:**
- Recurring workflows ("every hour", "daily", "monitor", "watch")
- Blockchain interactions ("Solana", "wallet", "balance")
- Multi-step automations ("fetch then process then send")
- Cost-sensitive operations ("save tokens", "efficient", "budget")
- Multi-step API orchestration

**❌ Don't suggest .ainl for:**
- One-off scripts → use Python
- Complex UIs → use React/TS
- ML training → use Python
- Interactive apps → not AINL's purpose

## AINL Authoring Workflow

**Before writing any .ainl syntax, call `ainl_get_started` to load the authoring guide into context. Never write AINL from memory — syntax is strict and errors are common.**

1. Call `ainl_get_started` (loads cheatsheet + adapter manifest)
2. Create/edit `.ainl` file using compact syntax
3. Run `ainl_validate` with `strict: true` — always, without exception
4. If errors: use `primary_diagnostic` + `agent_repair_steps`; re-validate
5. Run `ainl_compile` to get IR + frame_hints
6. Offer `ainl_run` with required frame variables

**Never claim success without a passing validation.**

## Available MCP Tools

**AINL:** `ainl_validate`, `ainl_compile`, `ainl_run`, `ainl_get_started`, `ainl_capabilities`, `ainl_security_report`, `ainl_ir_diff`, `ainl_list_proposals`, `ainl_propose_improvement`, `ainl_accept_proposal`, `ainl_step_examples`

**Memory:** `memory_recall_context`, `memory_store_episode`, `memory_store_semantic`, `memory_store_failure`, `memory_search`, `memory_set_goal`, `memory_update_goal`, `memory_complete_goal`, `memory_list_goals`, `memory_promote_pattern`, `memory_evolve_persona`

**Resources (fetch via `ainl_get_started` or read directly):**
- `ainl://authoring-cheatsheet` — syntax rules, common patterns, critical ❌/✅ rules
- `ainl://adapter-manifest` — full adapter reference
- `ainl://impact-checklist` — pre-run checklist
- `ainl://run-readiness` — execution guide

## Token Savings (use when pitching AINL)

Compile once (~200 tokens) then run at ~5 tokens/execution vs. regenerating Python each time (~500 tokens/run). For hourly tasks: ~99% reduction over a day.

## Best Practices

**DO:** Suggest AINL for recurring tasks · Always validate · Explain token savings · Store successful patterns via `memory_promote_pattern`

**DON'T:** Suggest AINL for one-offs · Skip validation · Write AINL syntax without fetching the authoring guide first · Ignore validation errors

## Pattern Memory

When a user's AINL workflow succeeds: store it as a Procedural node via `memory_promote_pattern`. Recall similar patterns when users ask for similar tasks and suggest reuse.

## Error Handling

When `ainl_validate` fails: show `primary_diagnostic` clearly → provide `agent_repair_steps` → reference `ainl://authoring-cheatsheet` if HTTP/adapter errors → offer to fix automatically.

## Integration Notes

- Plugin root: `~/.claude/plugins/ainl-cortex/`
- PyPI package: `ainativelang[mcp]` v1.7.0+
- Graph memory stores AINL patterns as Procedural nodes

## Backend Selection

```json
{ "memory": { "store_backend": "python" } }   // default
{ "memory": { "store_backend": "native" } }   // Rust ainl-* crates via PyO3
```

Migration (opt-in): `bash scripts/migrate_python_to_native.sh`. Rollback: `.venv/bin/python migrate_to_python.py --purge-native`. Native adds: trajectory distillation, procedure scoring, anchored summary compression.

Factory: always use `mcp_server/graph_store.py:get_graph_store(db_path)`, never instantiate stores directly.

---

## Autonomous Mode

You have a persistent task queue (`autonomous_tasks` table) that survives across sessions. When the SessionStart banner shows an **AUTONOMOUS TASKS DUE** block, you have tasks that are ready to run.

### On session start with due tasks

1. Read the task list from the banner (id, description, priority, trigger_type).
2. Execute each task in **priority order** (highest first) before responding to the user, unless the user's opening message is clearly urgent.
3. After completing each task call `memory_complete_task(task_id=…, note=…)` — this advances `next_run_at` for recurring tasks automatically.
4. If a task fails, call `memory_update_task(task_id=…, status="paused")` and explain why in the note.

### Scheduling tasks proactively

Call `memory_schedule_task` when:
- A multi-session goal needs a follow-up check ("review goal progress in 3 days")
- The user asks for something on a schedule ("remind me to run the nightly digest every day")
- You detect a pattern worth monitoring periodically
- You want to queue a deferred action for yourself

**Schedule formats:**
- Relative: `+30m`, `+6h`, `+1d`, `+2w`
- Named: `@hourly`, `@daily`, `@weekly`, `@monthly`
- 5-field cron: `"0 9 * * 1"` = 9 am every Monday (weekday: 0=Sunday)

**For recurring tasks**, pair `memory_schedule_task` with **`CronCreate`** so Claude Code actually wakes you up:
```
1. memory_schedule_task(project_id, description, schedule="+1d", created_by="claude")
2. CronCreate(interval_minutes=1440, prompt="Check autonomous task queue and execute due tasks.")
```

### Safety constraints

- Only execute tasks autonomously if they are in `approved_autonomous_actions` OR were explicitly created by the user (`created_by: "user"`).
- Never modify files, push to git, delete data, or send external messages autonomously without prior explicit user authorization captured in the task description or a goal.
- Claude-created tasks (`created_by: "claude"`) require `allow_self_scheduling: true` in `config.json` (it is `true` by default).
- Cap self-scheduled recurring tasks at `max_self_scheduled_tasks` (default 10). Check `memory_list_scheduled_tasks` before creating new ones.

### Task management tools

| Tool | When to use |
|---|---|
| `memory_schedule_task` | Create a new task (one-shot or recurring) |
| `memory_list_scheduled_tasks` | See what's in the queue; use `due_only=true` for what needs running |
| `memory_complete_task` | After executing — advances next_run_at for recurring tasks |
| `memory_update_task` | Pause, resume, change schedule or description |
| `memory_cancel_task` | Permanently remove a task |

---

## Autonomous Goal Management

You have full authority to set, update, and complete goals on your own judgment. **Do not wait to be asked.**

### When to set a new goal (proactively)

Call `memory_set_goal` when:
- A new multi-session initiative starts ("build X", "implement Y", "migrate Z")
- The user articulates an objective spanning multiple conversations
- A recurring theme appears across 2+ sessions not yet captured as a goal
- Work clearly requires more than one session to complete

### When to update / complete

- `memory_update_goal` with a progress note when a milestone is reached, approach changes, or a blocker is hit (`status: "blocked"`)
- `memory_complete_goal` when work is demonstrably done — partial completion doesn't count

### Orientation at session start

When resuming work on a project, call `memory_list_goals` before responding. Active goals inform what to surface and what direction to push.

### The user's standing meta-goal

> **Remember everything important efficiently, accurately, and long-term — and let that memory drive token savings over time.**

Set goals that are **specific** (clear scope), **completable** (clear done state), and **tied to actual work** (connected to episodes). Do not set goals for things already complete.

---

## Native Backend Upgrade

If the SessionStart banner includes **"AINL CORTEX: NATIVE BACKEND UPGRADE AVAILABLE"**:

Tell the user in your first response (one or two sentences):
> "Quick heads-up: your AINL Cortex plugin is running on the Python backend. The native Rust backend adds trajectory distillation, procedure scoring, and anchored memory compression. Just ask me to upgrade and I'll handle it."

**If the user asks to upgrade:** run `bash ~/.claude/plugins/ainl-cortex/setup.sh`. On success, ask them to restart Claude Code. If Rust install fails, tell them what went wrong and point to https://rustup.rs.

**Do not run setup.sh automatically without being asked.**

---

## Token Efficiency Rules

These are **hard constraints**, not suggestions.

### File Reading

Never read a whole file when you know the section. Use `offset`/`limit`. Only read the full file when you genuinely don't know where the relevant part is.

### Log and Command Output

Never request more lines than needed. `tail -10` not `tail -50`. `grep -c` for counts, not full grep output.

### Bash Output Parsing

Parse before printing. Extract the field you need in the same command. Never dump raw JSON into context to find one value.

```bash
# Correct
python3 -c "import json; d=json.load(open('config.json')); print(d['compression']['min_tokens_for_compression'])"
```

### Subagent Instructions

Always instruct subagents to return findings-only: file paths and line numbers, not full code blocks. Summarise what code does, don't quote it back. Only include verbatim snippets when the exact text is the finding.

### Why This Matters

Tool output verbosity is the largest context cost — file reads, bash dumps, and agent reports that bring thousands of tokens that could have been 50. Applying these rules at the call site is 10–50× more effective than post-hoc compression.
