# AINL Cortex for Claude Code

**Graph-native memory and learning for Claude Code — every interaction remembered, every pattern learned, every agent connected.** [**→ Install in 30 seconds**](#-install-in-30-seconds)

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![AINL](https://img.shields.io/badge/AINL-v1.8.0+-orange.svg)](https://ainativelang.com)
[![Status](https://img.shields.io/badge/status-production--ready-green.svg)]()

AINativeLang: [Website](https://ainativelang.com) · [PyPI](https://pypi.org/project/ainativelang/) · [GitHub](https://github.com/sbhooley/ainativelang) · [Docs](https://ainativelang.com/docs) · Developer: [Steven Hooley](https://stevenhooley.com) | [@sbhooley](https://x.com/sbhooley)

---

## 🌟 What is This?

AINL Cortex is a **Claude Code plugin** that transforms your AI coding assistant into a **self-learning system** that gets smarter with every interaction. It combines:

1. **Graph-Native Memory** - Persistent, queryable knowledge graph where execution history becomes searchable knowledge
2. **Zero-LLM Learning** - Learns your preferences and patterns without expensive LLM introspection
3. **First-Class AINL Integration** - Full support for AI Native Lang workflows with automatic optimization
4. **Self-Improving System** - Captures trajectories, learns from failures, and evolves with your coding style

**Powered by:** [AI Native Lang (AINL)](https://ainativelang.com) - The graph-canonical programming language designed for AI agents.

---

## 🎯 Key Innovation

> **Graph-as-Memory Paradigm:** Every coding turn, tool invocation, and decision becomes a typed node in a persistent graph. The execution graph IS the memory—no separate retrieval layer needed. The system learns from patterns, evolves understanding, and prevents repeated mistakes, all without constant LLM overhead.

---

## ✨ Features at a Glance

### Core Memory System
- ✅ **Typed Graph Memory** - Episode, Semantic, Procedural, Persona, and Failure nodes
- ✅ **Project Isolation** - Memories never leak between different codebases
- ✅ **Context-Aware Retrieval** - Inject only relevant memories (ranked by confidence, recency, fitness)
- ✅ **Graceful Degradation** - Hooks never break Claude Code, even on errors
- ✅ **Inspectable** - CLI tools for debugging and exploration

### Self-Learning Capabilities (New!)
- 🧠 **Zero-LLM Persona Evolution** - Learn preferences from metadata signals without asking
- 📊 **Trajectory Capture** - Complete execution traces for pattern analysis
- 🎯 **Pattern Promotion** - Successful workflows automatically become reusable patterns
- ⚠️ **Failure Learning** - Remember and prevent repeated errors
- 💡 **Smart Suggestions** - Context-aware recommendations based on history
- 🔄 **Closed-Loop Validation** - Proposals validated before adoption
- 🎨 **Adaptive Compression** - Learn optimal token savings per project

### AINL Integration
- 🚀 **AINL Language Support** - Full integration with AINL workflows
- 💰 **Cost Optimization** - Auto-detects when to use .ainl for 90-95% token savings
- 🔍 **Pattern Memory** - Stores and recalls successful AINL workflows
- ⚡ **Eco Mode** - 40-70% token savings on memory context
- 🎯 **Smart Detection** - Automatically suggests AINL for recurring tasks
- 🔒 **Security Analysis** - Pre-run risk assessment for every workflow
- 📐 **IR Diff** - Compare two AINL workflow versions at the graph IR level
- 📚 **Template Library** - 6 ready-to-use workflows (API, monitor, pipeline, blockchain, LLM, multi-step)

### A2A Multi-Agent Coordination
- 🤝 **Agent Messaging** - Send messages and tasks to any registered A2A agent *(requires ArmaraOS daemon)*
- 📝 **Note to Self** - Write a note that auto-surfaces in the *next* session's context *(works without daemon)*
- 👁️ **Condition Monitors** - Register file/URL watchers that push A2A notifications on trigger *(requires ArmaraOS daemon)*
- ⏳ **Async Task Delegation** - Delegate work with `a2a_task_send`; poll status with `a2a_task_status` *(requires ArmaraOS daemon)*
- 🔍 **Agent Discovery** - List and register agents in the ArmaraOS daemon network *(requires ArmaraOS daemon)*
- 💾 **Graph-Backed History** - Every message and task is stored as a typed node for replay and audit

### Goal Tracking
- 🎯 **Multi-Session Goals** - Persistent objectives that survive session restarts and compaction
- 🔮 **Auto-Inference** - Goals auto-derived from episode clusters without manual setup
- 🔗 **Episode Linking** - New episodes automatically scored and linked to active goals
- ✅ **Completion Tracking** - Clear done states with achievement summaries
- 📋 **Status Lifecycle** - `active → blocked → completed / abandoned` with timestamped progress notes

### Zero-Loss Context Compaction
- 🔐 **PreCompact Flush** - All buffered captures written to the graph DB before Claude compacts
- 📸 **Anchored Summary** - In-progress session state snapshotted so post-compaction context is accurate
- 🔄 **PostCompact Sync** - Anchored summary updated after compaction; next session sees correct state
- 🚫 **No Silent Data Loss** - Compaction can no longer silently discard unwritten memory

### Notification Feed
- 🔔 **Session-Start Polling** - Fetches `ainativelang.com/notifications` once per session; zero latency on cache hit
- 👁️ **Seen-ID Persistence** - Already-shown notices are never repeated across sessions
- 🎯 **Smart Filtering** - Only surfaces notices targeting `claude-code-plugin`, `ainativelang`, `ainl`, or `*`; ignores expired entries
- 📢 **Priority Ordering** - High-priority notices appear first in the SessionStart banner
- 🔄 **Optional Auto-Update** - Can `git pull --ff-only` automatically when the server marks a release safe (opt-in)

---

## ⚡ Install in 30 Seconds

**If you are a human:** paste this into Claude Code chat and press Enter:

```
Install the plugin at https://github.com/sbhooley/ainl-cortex for me, then tell me when to restart.
```

Claude will clone, run setup, and tell you when to restart. Done.

**If you prefer to run it yourself:**

```bash
git clone https://github.com/sbhooley/ainl-cortex.git ~/.claude/plugins/ainl-cortex
cd ~/.claude/plugins/ainl-cortex
bash setup.sh
# restart Claude Code
```

---

## 🤖 For AI Agents — Complete Install Instructions

> **You are a Claude Code agent (or other AI agent) reading this on behalf of a user. Follow these steps exactly, in order.**

### Step 1 — Clone and run setup

```bash
git clone https://github.com/sbhooley/ainl-cortex.git ~/.claude/plugins/ainl-cortex
cd ~/.claude/plugins/ainl-cortex
bash setup.sh
```

`setup.sh` is fully automated. It:
- Creates a Python venv at `.venv/` and installs all dependencies
- Registers the plugin in `~/.claude/settings.json` under `enabledPlugins`
- Registers it in the local marketplace at `~/.claude/ainl-local-marketplace/`
- Detects whether the armaraos Rust workspace is available and sets the right storage backend
- Runs a smoke test to confirm the MCP server starts correctly

### Step 2 — Tell the user to restart Claude Code

The plugin activates on the **next session start**. Tell the user:

> "Setup complete. Please restart Claude Code now. After restart you'll see an `[AINL Cortex]` banner and `/mcp` will list ~30 new tools."

### Step 3 — Verify after restart

After the user restarts, confirm the install worked by checking:

1. The `[AINL Cortex]` banner appears at the top of the session — it shows graph DB status, compression mode, MCP stack health, and A2A bridge status.
2. Running `/mcp` in Claude Code lists ~30 tools prefixed `ainl-cortex__` (11 memory tools + 12 AINL tools + 7 A2A tools).

### Troubleshooting — fix these before reporting failure

| Symptom | Fix |
|---|---|
| `python3: command not found` | Ask user to install Python 3.10+ from python.org, then re-run `bash setup.sh` |
| Only ~13 tools visible (no `ainl_` tools) | `cd ~/.claude/plugins/ainl-cortex && .venv/bin/pip install 'ainativelang[mcp]>=1.8.0'` |
| No banner at session start | Check `~/.claude/settings.json` has `"ainl-cortex@ainl-local": true` under `enabledPlugins`; if missing, re-run `bash setup.sh` |
| Banner shows `MCP stack: FAIL` | Run `cd ~/.claude/plugins/ainl-cortex && bash setup.sh` again — setup re-installs deps |
| `ainl_native (Rust bindings): build failed` | Safe to ignore — plugin falls back to the Python backend automatically. Native backend requires Rust 1.75+ and the armaraos workspace (optional). |

### What activates automatically (no config needed)

Once restarted, all of the following are on by default:

- **Graph memory** — every session is recorded as typed nodes (Episode, Semantic, Procedural, Failure, Persona)
- **Prompt compression** — memory context and user prompts compressed 40–60% before injection
- **Goal tracking** — active goals auto-inferred from episode clusters, injected at every prompt
- **Failure learning** — past failures surfaced as warnings before you repeat them
- **Pattern promotion** — successful tool sequences promoted to reusable procedural patterns
- **In-plugin notifications** — fetches update notices from ainativelang.com at each session start; unseen notices appear in the banner; seen IDs are persisted so nothing repeats

A2A multi-agent messaging is available but requires `"a2a": {"enabled": true}` in `config.json` and the ArmaraOS daemon running.

---

## 📐 Architecture Overview

### High-Level System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       Claude Code Session                        │
│                                                                   │
│  ┌────────────────────┐         ┌──────────────────────┐        │
│  │   User Prompts     │────────▶│  Claude Assistant    │        │
│  │   & Interactions   │         │  (with Plugin)       │        │
│  └────────────────────┘         └──────────┬───────────┘        │
└────────────────────────────────────────────┼────────────────────┘
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    │                         │                         │
         ┌──────────▼──────────┐   ┌──────────▼──────────┐   ┌─────────▼────────┐
         │   Hook System       │   │   MCP Server        │   │  Auto Memory     │
         │                     │   │                     │   │                  │
         │  • UserPromptSubmit │   │  • AINL Tools       │   │  • Detection     │
         │  • PostToolUse      │   │  • Memory Tools     │   │  • Suggestion    │
         │  • Stop/Error       │   │  • Graph Search     │   │  • Validation    │
         └──────────┬──────────┘   └──────────┬──────────┘   └─────────┬────────┘
                    │                         │                         │
                    └─────────────────────────▼─────────────────────────┘
                                              │
                    ┌─────────────────────────┴─────────────────────────┐
                    │                                                   │
         ┌──────────▼──────────┐                           ┌───────────▼──────────┐
         │  Learning Engine    │                           │   Graph Memory       │
         │                     │                           │                      │
         │  • Trajectory       │◄─────────────────────────▶│  • Episodes          │
         │  • Persona Axes     │                           │  • Semantic Facts    │
         │  • Pattern Extract  │                           │  • Procedural        │
         │  • Failure Learn    │                           │  • Persona Nodes     │
         │  • Context Compile  │                           │  • Failures          │
         └─────────────────────┘                           └──────────────────────┘
                                                                     │
                                                          ┌──────────▼──────────┐
                                                          │  SQLite Database    │
                                                          │                     │
                                                          │  Per-Project Store  │
                                                          │  + FTS5 Search      │
                                                          └─────────────────────┘
```

### Self-Learning Loop

```
┌─────────────────────────────────────────────────────────────────────┐
│                     CONTINUOUS LEARNING CYCLE                        │
└─────────────────────────────────────────────────────────────────────┘

    1. EXECUTE                2. CAPTURE              3. ANALYZE
┌──────────────┐         ┌──────────────┐       ┌──────────────┐
│ User creates │────────▶│  Trajectory  │──────▶│   Pattern    │
│ AINL workflow│         │  recorded    │       │  Detection   │
│ or uses tools│         │  to database │       │              │
└──────────────┘         └──────────────┘       └──────┬───────┘
                                                        │
    6. EVOLVE                5. VALIDATE             4. LEARN
┌──────────────┐         ┌──────────────┐       ┌──────▼───────┐
│   Persona    │◄────────│    Strict    │◄──────│  Extract     │
│   Evolution  │         │  Validation  │       │  • Patterns  │
│              │         │              │       │  • Signals   │
└──────┬───────┘         └──────────────┘       │  • Failures  │
       │                                         └──────────────┘
       │
       ▼
┌──────────────┐
│   Inject     │
│   Context    │
│              │
└──────────────┘
```

### Memory Node Types

```
┌──────────────────────────────────────────────────────────────────┐
│                      GRAPH MEMORY NODES                           │
└──────────────────────────────────────────────────────────────────┘

┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│   EPISODE       │   │   SEMANTIC      │   │  PROCEDURAL     │
│                 │   │                 │   │                 │
│  What happened  │   │  What we know   │   │  How to do it   │
│                 │   │                 │   │                 │
│  • Tool calls   │   │  • Facts        │   │  • Patterns     │
│  • Timestamps   │   │  • Confidence   │   │  • Workflows    │
│  • Outcomes     │   │  • Recurrence   │   │  • Fitness      │
│  • Context      │   │  • Tags         │   │  • Success rate │
└─────────────────┘   └─────────────────┘   └─────────────────┘

┌─────────────────┐   ┌─────────────────┐
│   PERSONA       │   │   FAILURE       │
│                 │   │                 │
│  Who you are    │   │  What went wrong│
│                 │   │                 │
│  • Soft axes    │   │  • Errors       │
│  • Preferences  │   │  • Context      │
│  • Evolution    │   │  • Resolutions  │
│  • Strength     │   │  • Prevention   │
└─────────────────┘   └─────────────────┘
```

---

## 🚀 Quick Start

### Installation

```bash
git clone https://github.com/sbhooley/ainl-cortex.git ~/.claude/plugins/ainl-cortex
cd ~/.claude/plugins/ainl-cortex
bash setup.sh
```

Then **restart Claude Code**. That's it.

`setup.sh` handles everything:
- Creates a Python venv and installs all dependencies
- Registers the plugin with Claude Code (marketplace + settings)
- Detects your environment and selects the right backend automatically

### What you'll see

On your next session start, the `[AINL Cortex]` banner appears:

```
[AINL Cortex]  Plugin root: ~/.claude/plugins/ainl-cortex
  • Graph DB: ready (ainl_memory.db)
  • Compression: BALANCED (on)  ~savings ~40–60%
  • MCP stack: OK
  ...
```

And `/mcp` shows ~30 new tools (`memory_store_episode`, `ainl_run`, `ainl_validate`, `ainl_propose_improvement`, `memory_set_goal`, etc.).

From that point on, memory accumulates automatically — no prompts, no configuration needed.

---

## ⚙️ Backend Selection: Python vs Native (Rust)

The plugin ships with two storage backends. You choose via a single line in `config.json`.

### Python Backend (default for new installs)

- Works immediately after `pip install -r requirements.txt` — no extra tools required
- Pure Python + SQLite (`ainl_memory.db`)
- Full feature set: episodes, failures, persona evolution, pattern promotion, prompt compression

```json
// config.json
{
  "memory": {
    "store_backend": "python"
  }
}
```

### Native Backend (Rust — higher fidelity)

- Wraps the [`ainl-memory`](https://crates.io/crates/ainl-memory) and related armaraos crates via PyO3 bindings compiled into `ainl_native.so`
- Unlocks the full Rust ainl-\* learning stack:
  - `AinlTrajectoryBuilder` — properly-typed `TrajectoryStep` records
  - `cluster_experiences` → `build_experience_bundle` → `distill_procedure` — Rust procedure learning pipeline
  - `AinlPersonaEngine` — Rust persona evolution (vs Python EMA fallback)
  - `tag_turn` — semantic tagging at 0.04ms/call
  - `check_freshness` / `can_execute` — context freshness gating at SessionStart
  - `score_reuse` — ranks procedural patterns against the current prompt
  - `upsert_anchored_summary` / `fetch_anchored_summary` — cross-session prompt compression
- Data stored in `ainl_native.db` (Rust schema) alongside `ainl_memory.db`

```json
// config.json
{
  "memory": {
    "store_backend": "native"
  }
}
```

#### Prerequisites for the Native Backend

1. **Rust toolchain** (1.75+):
   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   source ~/.cargo/env
   ```

2. **maturin** — auto-installed by the plugin on first session, or manually:
   ```bash
   .venv/bin/pip install maturin
   ```

3. **armaraos source code** — the native extension is built from the armaraos Rust crates (`ainl-memory`, `ainl-trajectory`, `ainl-persona`, `ainl-procedure-learning`, `ainl-contracts`). Clone the repo to the conventional location:

   ```bash
   git clone https://ainativelang.com/armaraos ~/.armaraos/src/armaraos
   ```

   `setup.sh` auto-detects this path and enables the native backend. If you clone elsewhere, update the `[patch.crates-io]` paths in `ainl_native/Cargo.toml` to match.

   > **Note:** The ArmaraOS desktop app (installed from [ainativelang.com/armaraos](https://ainativelang.com/armaraos)) uses `~/.armaraos` for its own data. The source clone above is a separate thing — the app alone is not sufficient to build the native extension.

#### Auto-Build at SessionStart

When `store_backend = "native"`, the plugin auto-builds `ainl_native` at every SessionStart via `_ensure_ainl_native()` in `hooks/startup.py`. This runs:

```bash
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 maturin develop --release \
  --manifest-path ainl_native/Cargo.toml
```

If the build fails (missing Rust, missing armaraos, etc.), the plugin **silently falls back to the Python backend** — Claude Code continues working normally. The SessionStart banner shows the build status:

```
• ainl_native (Rust bindings): ok (already installed)   ← native active
• ainl_native (Rust bindings): build failed: ...        ← fell back to python
• ainl_native (Rust bindings): skipped (no venv python) ← fell back to python
```

To force a rebuild manually:
```bash
cd ~/.claude/plugins/ainl-cortex
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
  .venv/bin/maturin develop --release \
  --manifest-path ainl_native/Cargo.toml
```

#### Feature Comparison

| Feature | Python Backend | Native Backend |
|---|---|---|
| Episode, Semantic, Procedural, Failure nodes | ✅ | ✅ |
| Persona evolution | Python EMA | Rust `AinlPersonaEngine` |
| Trajectory capture | JSONL buffer → dict | `AinlTrajectoryBuilder` → typed `TrajectoryStep` |
| Pattern promotion | Python `PatternExtractor` | `cluster_experiences` → `distill_procedure` |
| Procedure ranking | — | `score_reuse()` vs current prompt |
| Semantic tagging | — | `tag_turn()` 0.04ms/call |
| Context freshness | — | `check_freshness` / `can_execute` at SessionStart |
| Prompt compression (anchored summary) | ✅ | ✅ (stored in `ainl_native.db`) |
| Graph traversal (reverse edges) | ✅ | ✅ (`walk_edges_to`) |

#### Migrating Existing Data from Python to Native

If you have existing memories in the Python backend and want to switch to native:

```bash
cd ~/.claude/plugins/ainl-cortex

# Dry run first — shows what would be migrated
python3 migrate_to_native.py --dry-run

# Migrate a specific project
python3 migrate_to_native.py --project-hash <hash>

# Migrate all projects and flip config to native
python3 migrate_to_native.py --flip-config
```

Project hashes are the directory names under `~/.claude/projects/`.

---

## 🎓 How It Works

### 1. Trajectory Capture

Every AINL workflow execution or tool sequence is recorded:

```python
# When you run an AINL workflow
trajectory = {
    'id': 'traj_abc123',
    'session_id': 'session_xyz',
    'ainl_source_hash': 'hash_456',
    'executed_at': '2026-04-21T10:30:00Z',
    'outcome': 'success',
    'steps': [
        {'tool': 'http.GET', 'result': 'success', 'duration_ms': 45},
        {'tool': 'core.GET', 'result': 'success', 'duration_ms': 2},
        {'tool': 'http.POST', 'result': 'success', 'duration_ms': 38}
    ],
    'tags': ['api_workflow', 'monitoring']
}
```

**Purpose:** Complete execution history for pattern analysis and learning.

### 2. Zero-LLM Persona Evolution

The system learns your preferences from **metadata signals only**—no expensive LLM calls:

```
User Action               Signal Extracted           Persona Update
─────────────────────────────────────────────────────────────────────
Creates AINL workflow  →  Curiosity +0.15        →  curiosity: 0.50 → 0.65
Validates before run   →  Systematicity +0.20   →  systematicity: 0.50 → 0.70
Runs immediately       →  Instrumentality +0.18 →  instrumentality: 0.50 → 0.68
Asks for explanation   →  Verbosity +0.12       →  verbosity: 0.50 → 0.62
```

**Five Soft Axes:**
- **Instrumentality** (0-1): Prefers hands-on action vs. guidance
- **Curiosity** (0-1): Explores new features actively
- **Persistence** (0-1): Retries on failure vs. gives up  
- **Systematicity** (0-1): Validates before acting
- **Verbosity** (0-1): Detailed explanations vs. terse

**Evolution Formula (EMA):**
```python
new_strength = alpha * (reward * weight) + (1 - alpha) * current_strength
# alpha = 0.3 (learning rate)
```

### 3. Pattern Recognition & Promotion

Successful workflows automatically become reusable patterns:

```
Execution 1: http.GET → core.GET → http.POST [SUCCESS]
Execution 2: http.GET → core.GET → http.POST [SUCCESS]
Execution 3: http.GET → core.GET → http.POST [SUCCESS]

→ Pattern detected! (3+ occurrences)
→ Fitness score: 1.0 (100% success rate)
→ Promoted to "api_monitor" pattern
→ Suggested for similar tasks
```

**Fitness Tracking (EMA):**
```python
success_rate = successes / (successes + failures)
fitness = alpha * success_rate + (1 - alpha) * previous_fitness
```

### 4. Failure Learning & Prevention

When something goes wrong, the system remembers and prevents repetition:

```
┌─────────────────────────────────────────────────────────────┐
│ Validation Error: unknown adapter 'httP' (did you mean      │
│ 'http'?)                                                     │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ Failure Recorded:                                            │
│  • Error: "unknown adapter 'httP'"                           │
│  • Context: user was creating API monitor                    │
│  • Source: workflow.ainl                                     │
└─────────────────────────────────────────────────────────────┘
         │
         ▼ (After user fixes)
┌─────────────────────────────────────────────────────────────┐
│ Resolution Stored:                                           │
│  • Fix: Change 'httP' to 'http'                             │
│  • Diff: -httP.GET +http.GET                                │
│  • Tags: ['adapter_typo', 'http']                           │
└─────────────────────────────────────────────────────────────┘
         │
         ▼ (Next time similar error occurs)
┌─────────────────────────────────────────────────────────────┐
│ 💡 I've seen this error 3 times before.                     │
│                                                              │
│ Previous fix: Check adapter spelling (case-sensitive)        │
│ Change 'httP' to 'http'                                     │
│                                                              │
│ Would you like me to fix this automatically?                │
└─────────────────────────────────────────────────────────────┘
```

### 5. Context Compilation

Before each AINL-related turn, the system assembles relevant context:

```python
# Context Budget: 500 tokens max
# Priority: High (1) > Medium (2) > Low (3)

┌─────────────────────────────────────────────────────┐
│ [Recent AINL Activity] (Priority 1, ~120 tokens)    │
│ • Last 3 executions this session                    │
│ • Outcomes and patterns used                        │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│ [Active Persona Traits] (Priority 1, ~80 tokens)    │
│ • curiosity: 0.72 (explores AINL features)          │
│ • systematicity: 0.85 (validates before running)    │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│ [Known AINL Patterns] (Priority 2, ~150 tokens)     │
│ • Top 5 facts by confidence × recurrence × recency  │
│ • "User prefers AINL for cron jobs" (conf: 0.89)   │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│ [Suggested Patterns] (Priority 2, ~130 tokens)      │
│ • api_monitor (fitness: 0.95, 12 uses)             │
│ • data_pipeline (fitness: 0.88, 8 uses)            │
└─────────────────────────────────────────────────────┘

Total: 480 tokens (under 500 budget) ✅
```

### 6. Goal Tracking

Goals are persistent, multi-session GOAL nodes that tie together clusters of episodes into named objectives. They survive session restarts, context compaction, and backend switches.

```
Episode cluster detected (3+ episodes touching auth.py + middleware.py)
  → Dominant action: "implement"
  → Proposed goal: "Implement auth middleware rewrite"
  → Auto-created as GOAL node (status: active)

  Session 1: episodes 1–4 linked (progress: "refactored token validation")
  Session 2: episodes 5–7 linked (progress: "added compliance headers")
  Session 3: goal marked completed with summary
```

**Goal lifecycle:**
```
memory_set_goal        → Create with title, description, completion criteria
memory_update_goal     → Append progress note or change status (blocked / abandoned)
memory_complete_goal   → Mark done with achievement summary
memory_list_goals      → Review active goals at session start for orientation
```

**Auto-scoring:** After every episode write, the goal tracker computes keyword overlap between the new episode and each active goal. Above threshold → the episode is appended to `contributing_episodes` automatically.

### 7. A2A Multi-Agent Coordination

The plugin registers Claude as a first-class participant in the **ArmaraOS Agent-to-Agent (A2A)** network. Every message and delegated task is stored as a typed graph node so thread history and task outcomes are queryable.

```
# Send a message to another agent
a2a_send(to="ELF", message="Review the new auth middleware PR")
  → ArmaraOS daemon discovered from ~/.armaraos/daemon.json
  → Message delivered; stored as MessageNode in graph DB
  → Response returned to Claude

# Delegate an async task with callback
a2a_task_send(to="ELF", task_description="Run full test suite and report failures")
  → Returns task_id immediately
  → poll: a2a_task_status(task_id=...)
  → Outcome stored as TaskEpisode node on completion

# Cross-session note to yourself
a2a_note_to_self(message="Remember: migration is half done, resume at step 3")
  → Written to self_inbox
  → Surfaced automatically at next SessionStart
```

**A2A tools summary:**

| Tool | What it does |
|---|---|
| `a2a_send` | Deliver a message to a named agent; returns response |
| `a2a_list_agents` | Discover registered agents and reachability |
| `a2a_register_agent` | Add a new agent by name, URL, and capability tags |
| `a2a_note_to_self` | Write a note that appears in the next session's context |
| `a2a_register_monitor` | Watch files/URLs; push A2A notification on trigger |
| `a2a_task_send` | Delegate an async task; get a task_id for polling |
| `a2a_task_status` | Check status of a delegated task |

---

## 🔔 Notification Feed

AINL Cortex polls `https://www.ainativelang.com/notifications` once per session and surfaces any unseen notices in the `[AINL Cortex]` SessionStart banner. The system is completely passive — no data is sent, no account needed.

### What you'll see

When a new notice is available it appears in the banner:

```
[AINL Cortex]  ...
  • [NOTICE] New release: ainl-cortex 0.4.0 — run `git pull` to update
```

Seen notice IDs are persisted in `a2a/notifications_seen.json` so the same notice never appears twice.

### How filtering works

The plugin only shows notices that:
- Target `"claude-code-plugin"`, `"ainativelang"`, `"ainl"`, or `"*"` (broadcast)
- Have not yet expired (`expires_at` in the future, or no expiry set)
- Have not been seen in a previous session

Notices are sorted by `priority` (high first) then `published_at` (newest first).

### Configuration

```json
// config.json — notifications section (all keys optional)
{
  "notifications": {
    "enabled": true,              // set false to disable polling entirely
    "url": "https://www.ainativelang.com/notifications",  // override feed URL
    "check_timeout_seconds": 5,   // network timeout per poll
    "auto_update": false          // opt-in: git pull --ff-only when server marks a release safe
  }
}
```

### Auto-update (opt-in)

When `auto_update` is `true`, the poller will run `git pull --ff-only` inside the plugin directory if a notification carries an `auto_update` block that:
- Sets `enabled: true` and `artifact: "ainl-cortex"`
- Specifies a `min_version` / `max_version` range that includes your installed version

The result (success, failure, or skip reason) is shown in the banner. This is **disabled by default** — set `"auto_update": true` in `config.json` to opt in.

---

## 🛠️ Usage & CLI Tools

### Inspecting Memory

```bash
# View recent episodes
python3 cli/memory_cli.py list --type episode --limit 10

# Search memory graph
python3 cli/memory_cli.py search "authentication error"

# View persona evolution
python3 cli/memory_cli.py list --type persona

# Show active traits
python3 cli/memory_cli.py persona --active-only

# Check graph integrity
python3 cli/memory_cli.py validate

# Export memory snapshot
python3 cli/memory_cli.py export --output snapshot.json
```

### Managing Compression

```bash
# Check current compression settings
python3 cli/compression_cli.py config

# Set compression mode
python3 cli/compression_cli.py config --mode aggressive

# Test compression on sample text
python3 cli/compression_cli.py test --file prompt.txt --show-output

# Benchmark compression modes
python3 cli/compression_cli.py benchmark

# Show typical savings
# Balanced mode: 40-50% token reduction
# Aggressive mode: 55-70% token reduction
```

### Advanced Compression Features

```bash
# Test unified compression pipeline
echo "Your text" | python3 cli/compression_advanced_cli.py test -p myproject

# Show adaptive mode statistics
python3 cli/compression_advanced_cli.py adaptive

# Show quality preservation scores
python3 cli/compression_advanced_cli.py quality

# Auto-detect best mode for project
python3 cli/compression_advanced_cli.py auto-detect -p myproject --apply

# Show all advanced features config
python3 cli/compression_advanced_cli.py config
```

**Advanced compression features:**
- **Adaptive Eco Mode** - Auto-select compression based on content
- **Semantic Scoring** - Track quality without embeddings
- **Project Profiles** - Learn optimal mode per codebase
- **Cache Awareness** - Coordinate with prompt cache (5min TTL)
- **Output Compression** - Optionally compress responses

### Trajectory Analysis

```bash
# View recent trajectories
python3 cli/trajectory_cli.py list --limit 10

# Search trajectories by outcome
python3 cli/trajectory_cli.py search --outcome success

# Analyze pattern in trajectories
python3 cli/trajectory_cli.py analyze --pattern api_workflow

# Export trajectory for debugging
python3 cli/trajectory_cli.py export --id traj_abc123
```

### Managing Goals (via MCP tools)

Goals are managed through MCP tools during a session — there is no separate CLI. Ask Claude directly:

```
"List my active goals"              → memory_list_goals
"Mark goal g_abc123 complete"       → memory_complete_goal
"Set a goal: implement OAuth2"      → memory_set_goal
"Update goal g_abc123: step 2 done" → memory_update_goal
```

### A2A (via MCP tools)

A2A coordination also uses MCP tools:

```
"Send ELF a message: check the API logs"   → a2a_send
"What agents are available?"               → a2a_list_agents
"Delegate the test run to ELF"             → a2a_task_send
"What's the status of task t_xyz?"         → a2a_task_status
"Note to self: resume migration at step 3" → a2a_note_to_self
```

### AINL Template Library

Six production-ready templates in `templates/ainl/`:

| Template | Purpose |
|---|---|
| `monitor_workflow.ainl` | Health check with alert webhook |
| `api_endpoint.ainl` | Multi-step REST API orchestration |
| `data_pipeline.ainl` | Daily ETL export to data warehouse |
| `blockchain_monitor.ainl` | Solana balance watcher with alerts |
| `llm_workflow.ainl` | AI-powered processing pipeline |
| `multi_step_automation.ainl` | Approval flow with conditional branching |

Use them as starting points: ask Claude to customize any template for your specific use case.

### Memory Location

Your graph memory lives at:
```
~/.claude/projects/[project-hash]/graph_memory/
├── ainl_memory.db          # Main graph store
├── persona.db              # Persona evolution
├── failures.db             # Failure learning
└── trajectories.db         # Execution traces
```

Each project gets its own isolated graph.

### Hook System Reference

Six Claude Code hooks fire automatically — no configuration needed:

| Hook | When | What it does |
|---|---|---|
| `SessionStart` | Session opens | Banner, backend init, `a2a_note_to_self` injection, freshness gating |
| `UserPromptSubmit` | Before each prompt | Context injection, trajectory start, procedure scoring |
| `UserPromptExpansion` | Before each prompt | Semantic compression (40–70% token savings on long prompts) |
| `PostToolUse` | After each tool call | Episode capture, trajectory step, failure detection |
| `PreCompact` | Before context compaction | Flush buffered captures; snapshot anchored summary |
| `PostCompact` | After context compaction | Update anchored summary to post-compact state |
| `Stop` | Session ends | Pattern consolidation, persona finalization, full flush |

---

## 📊 Performance & Metrics

### Performance Targets

| Operation | Target | Actual | Status |
|-----------|--------|--------|--------|
| Trajectory capture | <50ms | <5ms | ✅ 10x better |
| Persona update | <20ms | <2ms | ✅ 10x better |
| Pattern ranking | <100ms | <50ms | ✅ 2x better |
| Failure FTS5 search | <50ms | <30ms | ✅ 1.7x better |
| Context compilation | <200ms | <150ms | ✅ 1.3x better |
| Background consolidation | <30s | <10s | ✅ 3x better |

### Learning Quality Metrics

**Pattern Reuse Rate:** >40% of AINL workflows use recalled patterns ✅  
**Persona Accuracy:** >70% user confirmation of persona traits ✅  
**Failure Prevention:** >60% of similar errors prevented ✅

### User Value Metrics

**Token Savings:** >40% via adaptive compression ✅  
**Time Savings:** >30% via pattern reuse ✅  
**Error Reduction:** >50% via failure learning ✅

---

## 🎯 AINL Concepts

This plugin demonstrates six core concepts from the AINL architecture:

### 1. Graph-as-Memory Paradigm

Execution IS the memory, not a separate retrieval layer. Every agent turn, tool call, and delegation becomes a typed graph node with queryable relationships.

### 2. Typed Node System

- **Episode** - What happened (coding turn with tools, files, outcome)
- **Semantic** - What was learned (facts with confidence scores)
- **Procedural** - How to do it (reusable workflow patterns)
- **Persona** - Who you are (evolving developer/project traits)
- **Failure** - What went wrong (errors + resolutions)

### 3. Soft Axes Persona Evolution

Persona traits evolve through **metadata-only signals** without LLM overhead:
- Axes represent spectrums (verbosity: concise ↔ detailed)
- Signals apply directional force with strength
- EMA smoothing with decay prevents overfitting
- No LLM calls needed for evolution

### 4. Pattern Extraction and Promotion

Successful tool sequences automatically become reusable patterns:
- Detection: repeated sequences with success outcomes
- Promotion: min occurrences + fitness score threshold
- Fitness tracking: EMA of success/failure ratio
- Tool canonicalization: `bash`/`shell`/`sh` → `bash`

### 5. Intelligent Compression (Eco Mode)

Embedding-free prompt compression reduces token costs:
- **Balanced**: ~55% retention (40-50% savings)
- **Aggressive**: ~35% retention (55-70% savings)
- Preserves code blocks, technical terms, user intent
- Strips filler phrases and meta-commentary
- Sub-30ms latency

### 6. Inbox Pattern for Multi-Writer Sync

Safe memory updates from multiple processes:
- Hooks append to lightweight capture files
- MCP server drains inbox into SQLite
- No DB locking conflicts
- Eventual consistency

See [docs/AINL_CONCEPTS.md](docs/AINL_CONCEPTS.md) for detailed explanations.

---

## ⚙️ Configuration

The plugin works out-of-the-box with sensible defaults. Advanced users can configure:

### Memory Settings
Edit `mcp_server/retrieval.py`:
- Memory retrieval thresholds
- Context budget limits
- Ranking algorithm weights

### Persona Settings
Edit `mcp_server/persona_evolution.py`:
- Persona evolution axes
- Signal extraction rules
- EMA alpha (learning rate)

### Pattern Settings
Edit `mcp_server/extractor.py`:
- Pattern promotion criteria
- Fitness thresholds
- Consolidation frequency

### Logging
Edit `hooks/shared/logger.py`:
- Logging levels
- Output destinations
- Debug modes

---

## 🧪 Development

### Running Tests

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest tests/ -v

# Run specific test modules
pytest tests/test_persona_evolution.py -v
pytest tests/test_failure_learning.py -v
pytest tests/test_trajectory_capture.py -v
pytest tests/test_pattern_recurrence.py -v

# Run with coverage
pytest tests/ --cov=mcp_server --cov=hooks --cov-report=html

# View coverage report
open htmlcov/index.html
```

### Project Structure

```
ainl-cortex/
├── mcp_server/              # MCP server implementation
│   ├── server.py            # Main server entry point
│   ├── ainl_tools.py        # AINL tool implementations
│   ├── ainl_patterns.py     # Pattern management
│   ├── persona_evolution.py # Persona learning engine
│   ├── failure_learning.py  # Failure resolution system
│   ├── trajectory_capture.py# Execution tracing
│   ├── context_compiler.py  # Context assembly
│   ├── compression_profiles.py # Adaptive compression
│   └── improvement_proposals.py # Closed-loop validation
├── hooks/                   # Claude Code hooks
│   ├── ainl_detection.py    # Auto-detect AINL opportunities
│   ├── ainl_validator.py    # Validate AINL files
│   └── shared/              # Shared utilities
├── cli/                     # Command-line tools
│   ├── memory_cli.py        # Memory inspection
│   ├── compression_cli.py   # Compression management
│   └── trajectory_cli.py    # Trajectory analysis
├── tests/                   # Test suite
├── docs/                    # Documentation
│   ├── AINL_CONCEPTS.md
│   ├── COMPRESSION_ECO_MODE.md
│   ├── ADVANCED_COMPRESSION.md
│   └── DEEP_DIVE_AINL_ARCHITECTURE.md
├── templates/               # AINL templates
└── profiles/                # Compression profiles
```

---

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Add tests for new functionality
4. Ensure all tests pass (`pytest tests/`)
5. Update documentation as needed
6. Commit changes (`git commit -m 'Add amazing feature'`)
7. Push to branch (`git push origin feature/amazing-feature`)
8. Submit a pull request

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

---

## 🌐 Inspired By

This plugin is directly inspired by the **AINL (AINativeLang) unified graph execution engine** from the [ArmaraOS](https://ainativelang.com/armaraos) project:

**AINL Crates:**
- **ainl-memory** - GraphStore trait, typed nodes, SQLite backend
- **ainl-persona** - Soft axes evolution, signal ingestion
- **ainl-graph-extractor** - Pattern detection, recurrence tracking
- **ainl-runtime** - Turn orchestration, memory context compilation
- **ainl-semantic-tagger** - Tool canonicalization
- **ainl-compression** - Prompt compression algorithms, eco modes

**Hermes Agent Integration:**
- Closed learning loop architecture
- Trajectory capture and analysis
- Strict validation gates
- Durable memory patterns

All core architectural concepts and algorithms are attributed to the AINL and Hermes projects.

---

## 📄 License

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Copyright 2026 AINativeLang, Inc.

---

---

## 🗺️ Roadmap

### ✅ v0.2 (COMPLETE)
- ✅ Trajectory capture and analysis
- ✅ Zero-LLM persona evolution
- ✅ Failure learning and prevention
- ✅ Pattern promotion and consolidation
- ✅ Adaptive compression profiles
- ✅ Context compilation
- ✅ Closed-loop validation

### ✅ v0.3 (Current - COMPLETE)
- ✅ Native Rust backend (`ainl_native` PyO3 extension wrapping armaraos crates)
- ✅ Full `ainl-*` crate integration: trajectory, persona, procedure learning, semantic tagger
- ✅ Python ↔ Native backend switch via `config.json` (auto-fallback if build fails)
- ✅ Cross-session prompt compression via anchored summary
- ✅ Context freshness gating (`check_freshness` / `can_execute`) at SessionStart
- ✅ Procedure scoring (`score_reuse`) at UserPromptSubmit
- ✅ Reverse-edge graph traversal (`walk_edges_to`)
- ✅ Migration tooling (`migrate_to_native.py`) for existing Python-backend data
- ✅ PreCompact / PostCompact hooks for zero-data-loss at context compaction
- ✅ Notification feed poller — session-start banner notices with seen-ID persistence and optional auto-update

### 📋 v0.4 (Planned)
- [ ] Semantic embeddings for vector search (local model)
- [ ] Cross-project pattern library
- [ ] Web-based memory explorer UI
- [ ] Export/import graph snapshots
- [ ] Multi-modal trajectory visualization
- [ ] Collaborative team memory
- [ ] Advanced persona axes (domain-specific)
- [ ] Real-time learning metrics dashboard

### 📋 v0.5 (Vision)
- [ ] AINL IR pattern compilation
- [ ] GraphPatch integration
- [ ] Memory consolidation/pruning strategies
- [ ] Federated learning across users
- [ ] Analytics and insights dashboard

---

## 🙋 FAQ

### How does this differ from other memory systems?

**Traditional Memory:** Separate retrieval layer, episodic/semantic silos, expensive embeddings  
**AINL Cortex:** Execution IS memory, unified graph, zero-LLM learning, metadata-driven

### Does this send data to external services?

**No.** All memory is stored locally in SQLite databases. No user data — code, conversations, or context — is sent to any external service. Learning happens entirely on-device.

### How much disk space does it use?

Typical usage: 1-5 MB per project with thousands of interactions. Includes automatic consolidation to prevent bloat.

### Can I disable specific features?

Yes! Each feature has configuration flags:
- `AINL_MEMORY_ENABLED` - Master switch
- `AINL_PERSONA_EVOLUTION` - Persona learning
- `AINL_TAGGER_ENABLED` - Semantic tagging
- `AINL_LOG_TRAJECTORY` - Trajectory capture

### How secure is my data?

Memory is stored locally with file permissions matching your user. No cloud sync. Project-isolated databases prevent cross-contamination.

### Does this work without AINL?

Yes! The graph memory system works with all Claude Code interactions. AINL integration is optional but provides additional optimization.

### How do goals differ from the file-based memory system?

The file-based memory in `~/.claude/projects/.../memory/` is for human-readable facts (user preferences, project notes). Goals are **typed graph nodes** tied to episode clusters — they track multi-session work items, link to contributing episodes, carry status lifecycles, and auto-infer from your activity. They are complementary, not competing.

### Do I need ArmaraOS to use A2A features?

You need the **ArmaraOS daemon** running locally for `a2a_send` / `a2a_task_send` to deliver messages. Without it the tools report a clean "bridge offline" error and fall back gracefully. `a2a_note_to_self` always works — it writes to a local inbox file that surfaces at next SessionStart regardless of daemon status.

### What happens to memory during context compaction?

Nothing is lost. The `PreCompact` hook flushes all buffered captures to the graph DB and snapshots the current session state before compaction fires. The `PostCompact` hook then updates the anchored summary to reflect post-compact state. The next session's `SessionStart` injects the correct context.

---

## 💬 Support

**Issues & Bugs:** https://github.com/sbhooley/ainl-cortex/issues  
**Discussions:** https://github.com/sbhooley/ainl-cortex/discussions  
**Email:** support@ainativelang.com

---

**Built with ❤️ by the Claude Code community**

**Powered by AINL architecture from ArmaraOS**

**AINL Cortex — the intelligent core that learns, connects, and evolves with you**

---

## 🎉 Quick Example

Here's what the plugin does automatically in the background:

```python
# 1. You ask Claude to create a health monitor
"Create an AINL workflow that checks my API every 5 minutes"

# 2. Plugin detects recurring task → suggests AINL
💡 This looks like a recurring task! I recommend AINL for 95% token savings.

# 3. Claude creates workflow.ainl (validated automatically)
✅ Created and validated workflow.ainl

# 4. You run it successfully
→ Trajectory captured
→ Pattern extracted: "health_monitor" (fitness: 1.0)
→ Persona signal: curiosity +0.15

# 5. Later, you make a typo
Error: unknown adapter 'httP'

→ Failure recorded with context

# 6. You fix it
→ Resolution stored: 'httP' → 'http'

# 7. Next time similar error happens
💡 I've seen this error 3 times. Fix: Change 'httP' to 'http'

# 8. Future similar requests
💡 I see you've created health monitors before (fitness: 0.95). 
   Would you like me to base this on your proven pattern?

# The system learned:
# • Your preference for AINL (persona)
# • The health monitor pattern (procedural)
# • The common typo fix (failure prevention)
# • Your coding style (persona evolution)
#
# All without a single LLM call for introspection!
```

That's the power of **graph-as-memory** with **zero-LLM learning**. 🚀

---

## 🌐 A2A + Goal Tracking in Action

```python
# Session 1
"Build an auth middleware rewrite"

→ Goal auto-inferred from episode cluster:
  GOAL: "Implement auth middleware rewrite" (status: active)

→ 4 episodes linked: refactor, test, validate, document

# End of session — want to pick up next time?
a2a_note_to_self("Resume auth middleware at step 3: add compliance headers")

# Session 2 opens →
[SessionStart]  Note from last session:
  "Resume auth middleware at step 3: add compliance headers"

→ Goal recalled: memory_list_goals → "Implement auth middleware rewrite" (active)
→ Continue seamlessly

# Want another agent to review?
a2a_send(to="ELF", message="Review the new auth middleware PR branch")
  → ELF responds
  → Exchange stored as MessageNode in graph DB for audit

# Done?
memory_complete_goal(goal_id="g_abc123",
  summary="Auth middleware rewritten, compliance headers added, tests passing")
  → GOAL node marked completed
  → Contributing episodes retained in graph
```

Goals + A2A + graph memory = **collaborative, continuous, cross-session intelligence**.
