# AINL Unified Graph Execution Engine Concepts

This document explains the core concepts from the AINativeLang (AINL) unified graph execution engine that inspire this Claude Code plugin.

## Vision: Execution Becomes Memory

**Traditional approach:**
```
Agent Execution ─→ Separate Memory Layer ─→ Retrieval System ─→ Context
```

**AINL approach:**
```
Execution Graph IS the Memory ─→ Graph Traversal ─→ Context
```

No impedance mismatch. No separate "memory consolidation" step. The execution trace itself is the queryable knowledge representation.

## 1. Graph-as-Memory Paradigm

### Principle

> The execution graph IS the memory, not a separate retrieval layer.

Every coding turn, tool invocation, and decision becomes a typed node in a persistent graph. There are no separate episodic/semantic/procedural silos—unified graph traversal provides all context retrieval needs.

### Why This Matters

**Traditional memory systems** store execution traces separately from semantic facts, then try to reconstruct causality during retrieval. This creates:
- Synchronization problems (when to consolidate?)
- Lossy compression (what to keep?)
- Retrieval mismatch (execution context lost)

**Graph-as-memory** eliminates these issues:
- Execution and memory are the same data structure
- Natural temporal ordering through graph edges
- Causality is first-class (FIXED_BY, DERIVES_FROM edges)
- Composable queries via graph traversal

### Implementation

In this plugin:
- Each `PostToolUse` hook creates potential episode nodes
- Tool sequences become FOLLOWS edge chains
- Semantic facts link to source episodes via DERIVES_FROM edges
- Patterns link to evidence via PATTERN_FOR edges

## 2. Typed Node System

Five core node types form the vocabulary of agent memory:

### Episode Node

**What happened during a coding turn.**

```python
{
    "turn_id": "uuid",
    "task_description": "Fix authentication bug",
    "tool_calls": ["read", "edit", "bash"],  # Canonicalized
    "files_touched": ["src/auth.py"],
    "outcome": "success"
}
```

- Records the **execution trace**
- Tool calls are **canonicalized** (`Bash`/`shell`/`sh` → `bash`)
- Outcome tracks success/failure/partial
- Links to previous episode via FOLLOWS edge

### Semantic Node

**What was learned as a fact.**

```python
{
    "fact": "Authentication requires JWT validation",
    "confidence": 0.85,
    "source_turn_id": "episode-uuid",
    "recurrence_count": 3,
    "tags": ["authentication", "security"]
}
```

- Facts have **confidence scores** (0.0-1.0)
- Recurrence count tracks repetition (increases confidence)
- Links to source episode via DERIVES_FROM edge
- Topic tags enable ranked retrieval

### Procedural Node

**How to do something as a reusable workflow.**

```python
{
    "pattern_name": "rust-cargo-check-fix-loop",
    "trigger": "cargo check error",
    "tool_sequence": ["bash", "read", "edit", "bash"],
    "success_count": 5,
    "fitness": 0.83  # EMA fitness score
}
```

- Represents **compiled workflows**
- Fitness tracked via EMA (Exponential Moving Average)
- Success/failure counts inform promotion decisions
- Links to evidence episodes via PATTERN_FOR edges

### Persona Node

**Who I am / What this project is.**

```python
{
    "trait_name": "prefers_explicit_types",
    "strength": 0.75,
    "axis": "type_safety",
    "layer": "adaptive"
}
```

- Traits evolve from **metadata signals** (no LLM calls)
- Strength decays over time without reinforcement
- Axes represent spectrums (concise ↔ detailed)
- Links to evidence episodes via LEARNED_FROM edges

### Failure Node

**What went wrong and how it was fixed.**

```python
{
    "error_type": "compilation",
    "tool": "bash",
    "error_message": "missing field `user_id`",
    "file": "src/models.rs",
    "line": 42,
    "resolution": "Added user_id field",
    "resolution_turn_id": "fix-episode-uuid"
}
```

- Captures **error details** with context
- Links to fix episode via RESOLVES edge
- Enables "known issues" retrieval
- Prevents repeated mistakes

## 3. Soft Axes Persona Evolution

### The Problem with Hard Traits

Traditional agent personas use binary traits:
- "Prefers concise responses" (on/off)
- Requires manual configuration
- No adaptation to changing context

### Soft Axes Solution

Persona traits live on **continuous spectrums**:

```
verbosity:        concise ←───────○─────→ detailed
                                   0.3 (slightly concise)

testing_rigor:    minimal ←─────────────○→ comprehensive
                                        0.85 (very thorough)
```

### Evolution via Metadata Signals

**No LLM calls needed.** Signals extracted from tool usage:

```python
# User ran 3 test commands in this session
signal = EvolutionSignal(
    axis='testing_rigor',
    direction=1.0,      # Toward "comprehensive"
    strength=0.7,       # Strong signal
    evidence='episode-uuid'
)

# Apply signal with EMA smoothing
axis.current = axis.current * 0.95 + signal * 0.05
```

### EMA Smoothing

Exponential Moving Average prevents overfitting:
- Recent behavior has more weight
- Old traits decay without reinforcement
- Noise doesn't create permanent traits (threshold)

### Example Axes

**Developer preferences:**
- `verbosity`: concise ↔ detailed
- `testing_rigor`: minimal ↔ comprehensive
- `type_safety`: dynamic ↔ strict
- `error_handling`: permissive ↔ defensive

**Project style:**
- `architecture`: monolithic ↔ modular
- `documentation`: sparse ↔ rich
- `performance_focus`: dev_speed ↔ optimization

## 4. Pattern Extraction and Promotion

### Automatic Workflow Learning

Successful tool sequences become **reusable patterns**:

```
Sequence observed 3 times:
  bash → read → edit → bash
  (all outcomes: success)

↓ Promote to pattern

Procedural node:
  name: "error-read-fix-verify"
  trigger: "compilation error"
  fitness: 0.90
```

### Promotion Criteria

- **Min occurrences**: 2+ successful executions
- **Min fitness**: 0.7+ success rate
- **Min sequence length**: 2+ tools (avoid trivial patterns)

### Tool Canonicalization

Before pattern detection, tools are **normalized**:

```python
TOOL_CANON = {
    'Bash': 'bash',
    'Shell': 'bash',
    'sh': 'bash',
    # ... more mappings
}
```

This ensures `[Bash, Read, Edit]` and `[shell, read, Edit]` are recognized as the same pattern.

### Fitness Tracking

Fitness uses **EMA** to track success rate:

```python
# Pattern used successfully
new_fitness = 0.2 * 1.0 + 0.8 * old_fitness

# Pattern failed
new_fitness = 0.2 * 0.0 + 0.8 * old_fitness
```

Low-fitness patterns are **not promoted** to avoid noise.

## 5. Inbox Pattern for Multi-Writer Sync

### The Challenge

Multiple processes need to write to graph memory:
- Hooks (fast, triggered by events)
- MCP server (authoritative, handles queries)
- Pattern extraction (background job)

Direct SQLite writes from all processes → locking conflicts.

### Inbox Solution

```
┌──────┐                  ┌──────────┐                  ┌─────────┐
│ Hook │ ─► append ────► │  Inbox   │ ─► drain ──────► │ SQLite  │
└──────┘   (no lock)     │  (JSONL) │   (transactional)│  Graph  │
                          └──────────┘                  └─────────┘
```

**Hooks:**
- Append lightweight JSON to `inbox/project_captures.jsonl`
- Never block on DB locks
- Always return immediately

**MCP Server:**
- Drains inbox on queries (eventual consistency)
- Consolidates captures into proper graph nodes
- Handles all DB transactions

**Benefits:**
- No locking conflicts
- Hooks remain fast and reliable
- Graph remains consistent (single writer)

### Inspired by AINL

This pattern mirrors ArmaraOS's approach:
- Python AINL writes to `ainl_graph_memory_inbox.json`
- Rust daemon drains inbox on turn start
- Separate projections remain eventually consistent

## 6. Context-Aware Retrieval

### Ranking Algorithm

When recalling context, nodes are **ranked** by relevance:

```python
score = 0.0

# Project match (critical)
if node.project_id == current_project:
    score += 10.0

# Recency (decay over 30 days)
age_days = (now - node.created_at) / 86400
score += 5.0 * (1 - age_days / 30)

# Type-specific bonuses
if node.type == 'episode' and node.outcome == 'success':
    score += 3.0
if node.type == 'procedural':
    score += node.fitness * 2.0
if node.type == 'semantic':
    score += node.recurrence_count * 0.3

# File/topic overlap
overlap = len(context_files & node_files)
score += overlap * 2.0

# Confidence multiplier
score *= node.confidence
```

### Working Memory Brief

Only the **top-ranked nodes** are injected:

```markdown
## Relevant Graph Memory

**Recent Work:**
- [2026-04-19] Fix auth bug in login.py → success
- [2026-04-18] Add JWT validation → success

**Known Facts:**
- JWT tokens require secret validation (conf: 0.92)
- Auth middleware runs before route handlers (conf: 0.85)

**Reusable Patterns:**
- "error-read-fix-verify": bash → read → edit → bash (fitness: 0.88)

**Known Issues:**
- src/auth.py:42: Unclosed session in logout handler

**Project Style:** testing_rigor (0.78), type_safety (0.65)
```

**Budget:** ~800 tokens to preserve Claude's context for reasoning.

## 7. Graceful Degradation

### Reliability Over Cleverness

The system is designed to **never break Claude Code**:

```python
# Every hook ALWAYS exits 0
try:
    # ... hook logic ...
except Exception as e:
    log_error(e)
    print(json.dumps({}))  # Empty response
finally:
    sys.exit(0)  # Always succeed
```

### Failure Modes

- **Hook script error** → Empty output, Claude continues
- **MCP server unavailable** → Retrieval returns empty context
- **Database corruption** → Validation warns, queries degrade gracefully
- **Memory over budget** → Brief is truncated with notice

**Philosophy:** A coding assistant with degraded memory is still useful. A coding assistant that crashes is not.

---

## Comparison to Traditional Memory Systems

| Aspect | Traditional RAG | AINL Cortex |
|--------|----------------|-------------------|
| **Storage** | Vector DB + metadata | Typed graph nodes + edges |
| **Retrieval** | Embedding similarity | Graph traversal + ranking |
| **Context** | Flat chunks | Structured episode → fact → pattern hierarchy |
| **Evolution** | Static embeddings | Dynamic persona + pattern fitness |
| **Causality** | Implicit in timestamps | Explicit in graph edges |
| **Composability** | Limited (chunk boundaries) | Natural (graph operations) |
| **Tool sequences** | Lost in consolidation | First-class procedural nodes |
| **Multi-writer** | Lock contention | Inbox pattern (eventual consistency) |

---

## Learn More

- **ArmaraOS Architecture**: https://ainativelang.com/armaraos/blob/main/ARCHITECTURE.md
- **AINL Cortex Guide**: https://github.com/sbhooley/ainl-cortex
- **ainl-memory crate**: https://crates.io/crates/ainl-memory
- **ainl-persona crate**: https://crates.io/crates/ainl-persona
- **ainl-runtime crate**: https://crates.io/crates/ainl-runtime

---

**These concepts are attributed to the AINL (AINativeLang) project.**

This plugin is a practical demonstration of how these principles can enhance coding assistants like Claude Code.
