# Deep Dive: AINL/ArmaraOS Architecture & Self-Learning Patterns

**Date:** 2026-04-21  
**Purpose:** Understand the graph-native architecture powering AINL and identify self-learning patterns to integrate into Claude Code

---

## Executive Summary

AINL (AI Native Lang) + ArmaraOS represent a **graph-as-memory** architecture where **execution IS the memory**, not a separate retrieval layer. Every agent turn, tool call, and delegation becomes a typed graph node, enabling:

1. **Zero-LLM persona evolution** via metadata-only signals
2. **Pattern extraction and promotion** from execution history
3. **Closed learning loops** via trajectory tapes and memory integration
4. **Context-aware retrieval** with fitness scoring and semantic ranking

**Key Innovation:** The graph doesn't just store what happened—it learns from execution patterns and evolves agent behavior without constant LLM invocations.

---

## Part 1: AINL/ArmaraOS Core Architecture

### 1.1 Graph-as-Memory Paradigm

**Core Principle:** The execution graph IS the memory, not a separate retrieval layer.

**Implementation:**
- Every agent turn → Episode node
- Every learned fact → Semantic node  
- Every successful pattern → Procedural node
- Every behavioral trait → Persona node
- Every failure → Failure node with resolution

**Storage:** SQLite per agent at `~/.armaraos/agents/<agent_id>/ainl_memory.db`

**Advantage over traditional memory:**
- No episodic/semantic/procedural silos
- Unified graph traversal for context retrieval
- Edges capture relationships between nodes
- Temporal queries via timestamps
- Confidence scoring on semantic facts

### 1.2 Typed Node System (ainl-memory)

**5 Core Node Types:**

```rust
// From ainl-memory crate
pub enum AinlNodeType {
    Episode,    // What happened (tool calls, delegations)
    Semantic,   // What was learned (facts with confidence)
    Procedural, // How to do it (reusable patterns)
    Persona,    // Who I am (evolving traits)
    Failure,    // What went wrong (errors + resolutions)
}
```

**Episode Nodes:**
- `turn_id`, `timestamp`, `tool_calls[]`, `delegation_to`
- Optional `trace_event` (OrchestrationTraceEvent as JSON)
- Optional `tags[]` (semantic labels from ainl-semantic-tagger)
- Records EVERY agent turn automatically

**Semantic Nodes:**
- `fact`, `confidence` (0.0-1.0), `source_turn_id`
- Optional `tags[]`, `recurrence_count`
- Extracted automatically via ainl-graph-extractor
- Ranked by confidence + recency + reference count

**Procedural Nodes:**
- `pattern_name`, `compiled_graph`, `fitness_score`
- Tracks `uses`, `successes`, `failures`
- EMA-based fitness scoring (success/failure ratio)
- Auto-promoted from repeated successful sequences

**Persona Nodes:**
- Two types:
  1. Human-facing traits (e.g., `prefers_brevity`, strength 0.0-1.0)
  2. Axis evolution bundle (soft axes snapshot, single row named `axis_evolution_snapshot`)
- Soft axes: Instrumentality, Curiosity, Persistence, Systematicity, Verbosity
- Evolved via weighted EMA from execution signals
- **No LLM calls required** - pure metadata analysis

**Failure Nodes:**
- Records errors with context
- Stores resolutions when found
- Prevents repeated mistakes

### 1.3 Persona Evolution (ainl-persona)

**The Magic:** Persona traits evolve from **metadata-only signals**—no LLM self-evaluation needed.

**How Soft Axes Work:**

```rust
// Example signals from tool usage
shell_exec → Instrumentality bump (hands-on action)
agent_delegate → Curiosity bump (exploring delegation)
file_read before edit → Systematicity bump (methodical)
```

**Evolution Engine:**
1. Extract `RawSignal` from graph nodes (tools used, delegation patterns, etc.)
2. Apply weighted EMA updates to axis scores (bounded [0, 1])
3. Persist evolution snapshot as Persona node
4. Inject traits into system prompt on next turn

**Key Features:**
- Correction tick: axes drift toward 0.5 when graph goes quiet
- Evolution cycle counter tracks learning progression
- Opt-out via `AINL_PERSONA_EVOLUTION=0`
- Default on with `ainl-persona-evolution` feature

**Example Evolution:**
```
Turn 1: User asks to run shell command
→ Record Episode: tool_calls = ["shell_exec"]
→ Spawn PersonaEvolutionHook
→ Extract signal: Instrumentality +0.15
→ Update axis via EMA
→ Persist snapshot
→ Next turn: system prompt includes "[Persona traits active: instrumentality (strength=0.62)]"
```

### 1.4 Pattern Extraction (ainl-graph-extractor)

**Two-Phase Extraction:**

**Phase 1: Semantic Recurrence**
- Detects repeated facts across episodes
- Bumps `recurrence_count` on semantic nodes
- Identifies patterns worth promoting

**Phase 2: Procedural Promotion**
- Finds tool sequences that repeat successfully
- Calculates fitness score (EMA of success/failure ratio)
- Creates Procedural nodes when fitness > threshold
- Enables one-click "apply pattern" in dashboard

**ExtractionReport Structure:**
```rust
pub struct ExtractionReport {
    merged_signals: Vec<RawSignal>,
    facts_written: Option<usize>,
    extract_error: Option<String>,
    pattern_error: Option<String>,
    persona_error: Option<String>,
}
```

**Graceful Degradation:**
- Each phase independent (partial failures don't cascade)
- `has_errors()` check for any failures
- Warnings logged, execution continues
- Same report structure in ainl-runtime

### 1.5 Context Retrieval & Injection

**Memory Blocks Assembled Per Turn:**

1. **RecentAttempts** - Recent episodic/tool summaries (session-first, strict caps)
2. **KnownFacts** - Ranked semantic facts (confidence + recurrence + recency)
3. **KnownConflicts** - Contradiction notes for conflicting high-confidence facts
4. **SuggestedProcedure** - Advisory procedural hints (fitness/success_rate, non-retired only)

**Ranking Algorithm:**
- Confidence × Recurrence × Recency weight
- Project-aware isolation (memories don't leak)
- Fail-closed (low-quality memory skipped)
- Conservative truncation to preserve context budget

**Control Plane:**
- Per-block kill switches (episodic, semantic, conflicts, procedural)
- Temporary mode (disable for specific turns via metadata)
- Global gate `AINL_MEMORY_ENABLED`
- Rollout gate `AINL_MEMORY_ROLLOUT` (off/internal/opt_in/default)

### 1.6 Compression & Eco Mode (ainl-compression)

**Problem:** Graph memory can be verbose, burning tokens.

**Solution:** Adaptive compression with quality preservation.

**Three Modes:**
- **Off:** No compression
- **Balanced:** ~55% retention (40-50% token savings)
- **Aggressive:** ~35% retention (55-70% token savings)

**Preserves:**
- Code blocks
- Technical terms
- User intent
- Semantic meaning

**Strips:**
- Filler phrases
- Meta-commentary
- Redundant context

**Sub-30ms latency** - embedding-free algorithm.

**Advanced Features (v0.2+):**
- Adaptive mode (auto-select based on content)
- Semantic scoring (track quality without embeddings)
- Project profiles (learn optimal mode per codebase)
- Cache awareness (coordinate with 5min prompt cache TTL)

### 1.7 Semantic Tagging (ainl-semantic-tagger)

**Purpose:** Deterministic semantic labels for episode and semantic nodes.

**Features:**
- Tool canonicalization (bash/shell/sh → bash)
- Concept extraction from tool sequences
- No LLM calls (rule-based + pattern matching)
- Opt-in via `AINL_TAGGER_ENABLED=1` (exact value required)

**Integration:**
- Tags added to Episode nodes on write
- Tags added to Semantic nodes during extraction
- FTS5 search enabled on tags
- Improves recall precision

### 1.8 Turn Orchestration (ainl-runtime)

**Optional higher-level runtime** layering the same SQLite GraphMemory.

**Features:**
- Sync `run_turn` / async `run_turn_async` (with Tokio feature)
- Nested delegation depth enforcement (internal, not soft status)
- `RuntimeStateNode` persistence (turn_count, extraction tracking)
- GraphPatch adapter system (procedural pattern dispatch)
- TurnOutcome with warnings (extraction/pattern/persona phases)

**Delegation Depth:**
```rust
// Enforced INSIDE ainl-runtime
max_delegation_depth: 8 (default)
Error: AinlRuntimeError::DelegationDepthExceeded
// TurnInput::depth is metadata only
```

**Not on live ArmaraOS chat path yet** - optional integration via `ainl-runtime-engine` feature.

**When to use:**
- Tests requiring full orchestration
- Tooling needing procedural dispatch
- Standalone AINL execution environments

---

## Part 2: Hermes Agent Self-Learning Architecture

### 2.1 What is Hermes Agent?

**Upstream:** [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research

**Core Concept:** Skill-native agent runtime with **closed learning loop**.

**Key Components:**
1. Skill system (modular capabilities)
2. Honcho memory (durable memory surface)
3. Trajectory capture (execution tapes)
4. Self-improvement loop (propose → validate → adopt)

### 2.2 Closed Learning Loop

**The Flow:**

```
1. Execute → 2. Capture Trajectory → 3. Store in Memory → 
4. Analyze Patterns → 5. Propose Improvements → 6. Validate → 
7. Adopt if Valid → (loop)
```

**Phase 1: Execute**
- Hermes runs skills (including AINL workflows via `ainl_run` MCP tool)
- Deterministic execution at AINL boundary
- Hermes orchestrates above, AINL deterministically executes below

**Phase 2: Capture Trajectory**
- AINL writes trajectory JSONL "tape" when `AINL_LOG_TRAJECTORY=1`
- Each step logged: tool calls, inputs, outputs, timestamps, outcomes
- Complete execution trace for learning

**Phase 3: Store in Memory (Honcho)**
- Bridge ingests tapes into Honcho (Hermes' durable memory)
- Persistent across sessions
- Queryable for pattern analysis

**Phase 4: Analyze Patterns**
- Hermes analyzes execution history
- Identifies repeated patterns, success/failure signals
- Correlates with user feedback and outcomes

**Phase 5: Propose Improvements**
- Hermes evolves candidate improvements:
  - New prompts
  - Refined control flow
  - Better tool sequences
  - Optimized steps

**Phase 6: Validate**
- Export candidate back to `.ainl`
- Run `ainl check candidate.ainl --strict`
- **Gate:** Only strict-mode-valid workflows promoted

**Phase 7: Adopt if Valid**
- Replace skill bundle in `~/.hermes/skills/ainl-imports/`
- New version available for next execution
- Old version archived

**Key Insight:** Learning loop is **above** the deterministic boundary. AINL provides auditability, Hermes provides evolution.

### 2.3 What Makes Hermes Good at Self-Learning

**1. Durable Memory (Honcho)**
- Not just ephemeral context
- Persistent across sessions
- Queryable history
- Pattern detection from long-term data

**2. Trajectory Tapes**
- Complete execution traces
- Every step logged
- Easy to replay/debug
- Rich data for learning

**3. Skill-Native Design**
- Modular capabilities
- Easy to add/remove skills
- Skills can call other skills
- Composability enables complexity

**4. Strict Validation Gate**
- All improvements must pass validation
- Prevents degradation
- Maintains determinism
- Auditability preserved

**5. Closed Loop**
- Continuous improvement
- No manual intervention needed
- Feedback incorporated automatically
- Gets better over time

### 2.4 AINL + Hermes Integration

**Why They're Perfect Together:**

| Hermes Strength | AINL Strength | Combined Benefit |
|-----------------|---------------|------------------|
| Learning loop | Determinism | Self-improving yet auditable |
| Memory (Honcho) | Graph memory | Multi-layer context |
| Skill system | Procedural nodes | Pattern reuse |
| Evolution | Strict validation | Safe improvement |
| Trajectory capture | Execution trace | Complete history |

**Integration Points:**

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  ainl:
    command: ainl-mcp
    args: []
```

**Hermes Skill Bundle Structure:**
```
~/.hermes/skills/ainl-imports/my-skill/
├── SKILL.md           # AgentSkills-style markdown
├── workflow.ainl      # AINL source
└── ir.json            # Canonical IR
```

**Execution Flow:**
1. Hermes decides to use skill
2. Calls `ainl_run` MCP tool with AINL source
3. AINL executes deterministically
4. Trajectory written to tape
5. Bridge ingests to Honcho
6. Hermes learns from execution

---

## Part 3: Self-Learning Patterns to Adopt

Based on the deep dive, here are the best patterns to integrate into Claude Code's AINL plugin:

### Pattern 1: Trajectory Capture & Analysis

**What Hermes Does:**
- Writes JSONL trajectory tapes with every execution step
- Stores in Honcho for pattern analysis

**Adapt for Claude Code:**
- Create `trajectory_capture.py` in plugin
- Log every AINL execution: tools used, frame vars, outcomes, timing
- Store in SQLite at `~/.claude/projects/<hash>/graph_memory/ainl_trajectories.db`
- Schema:
  ```sql
  CREATE TABLE trajectories (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    ainl_source_hash TEXT,
    executed_at TEXT,
    outcome TEXT,  -- success/failure
    steps JSONL,   -- full execution trace
    tags TEXT[]    -- extracted patterns
  );
  ```

### Pattern 2: Automatic Pattern Promotion

**What ArmaraOS Does:**
- `ainl-graph-extractor` detects repeated tool sequences
- Promotes to Procedural nodes with fitness scoring
- Auto-suggests patterns for similar tasks

**Adapt for Claude Code:**
- After AINL execution, scan for:
  - Repeated adapter sequences (e.g., http.GET → core.GET → http.POST)
  - Successful workflows (outcome = success)
  - Common frame variable patterns
- When pattern repeats 3+ times with >70% success rate:
  - Create pattern in `ainl_patterns` table (already exists)
  - Set initial fitness = success_rate
  - Tag with adapters used
- On similar user prompts:
  - Recall matching patterns via FTS5
  - Suggest: "I've seen this pattern before - use the 'api_monitor' template?"

### Pattern 3: Soft Axes Persona Evolution (Zero-LLM Learning)

**What ainl-persona Does:**
- Tracks Instrumentality, Curiosity, Persistence, Systematicity, Verbosity
- Updates via weighted EMA from tool usage signals
- No LLM calls needed

**Adapt for Claude Code:**
- Create `persona_axes.py` in plugin
- Track per-project axes:
  ```python
  class PersonaAxes:
      instrumentality: float  # 0-1, prefers hands-on tools
      curiosity: float       # 0-1, explores new features
      persistence: float     # 0-1, retries on failure
      systematicity: float   # 0-1, validates before acting
      verbosity: float       # 0-1, detailed vs terse
  ```
- Signal extraction:
  ```python
  # User creates AINL workflow → curiosity +0.1
  # User uses validation → systematicity +0.15
  # User creates hourly cron → persistence +0.1
  # User runs workflow immediately → instrumentality +0.2
  ```
- Apply EMA updates (alpha = 0.3)
- Store in `persona_nodes` table
- Inject into Claude's context:
  ```
  [User Persona Traits]
  - curiosity: 0.72 (actively explores AINL features)
  - systematicity: 0.85 (validates before running)
  - instrumentality: 0.45 (prefers guidance over doing)
  ```

### Pattern 4: Semantic Fact Recurrence Tracking

**What ainl-graph-extractor Does:**
- Bumps `recurrence_count` on semantic facts
- Ranks facts by confidence × recurrence × recency
- Surfaces high-signal facts in prompts

**Adapt for Claude Code:**
- When user creates successful AINL workflow:
  - Extract semantic facts (adapters used, patterns, frame vars)
  - Check if fact already exists (FTS5 search)
  - If exists: bump recurrence_count, update last_seen
  - If new: create with recurrence_count = 1
- Retrieval ranking:
  ```python
  def rank_facts(facts):
      return sorted(facts, key=lambda f: 
          f.confidence * 
          (1 + log(f.recurrence_count)) * 
          recency_weight(f.last_seen)
      )
  ```
- Inject top 5 facts into Claude's context before AINL tasks

### Pattern 5: Failure → Resolution Learning

**What ArmaraOS Does:**
- Records failures with context in Failure nodes
- Stores resolutions when found
- Prevents repeated mistakes

**Adapt for Claude Code:**
- When AINL validation fails:
  ```python
  failure_node = {
      'id': uuid4(),
      'error': diagnostic['error'],
      'ainl_source': source,
      'context': {
          'user_prompt': prompt,
          'suggested_approach': approach,
      },
      'resolution': None,  # filled when fixed
      'prevented_count': 0
  }
  ```
- When user fixes it (validation passes):
  - Update failure_node with resolution
  - Store diff between failed → fixed source
  - Tag with error type
- On future similar errors:
  - Recall matching failures via FTS5
  - Suggest resolution: "I've seen this error before. The fix was: ..."
  - Increment prevented_count

### Pattern 6: Context-Aware Compression

**What ainl-compression Does:**
- Adaptive eco mode (balanced/aggressive)
- Project profiles (learns optimal mode per codebase)
- Cache awareness (5min TTL coordination)

**Adapt for Claude Code:**
- Create `compression_profiles.py`
- Track per-project compression stats:
  ```python
  class CompressionProfile:
      project_id: str
      optimal_mode: str  # off/balanced/aggressive
      avg_token_savings: float
      quality_score: float
      last_tuned: datetime
  ```
- Auto-detect best mode:
  - Start with balanced
  - Track user corrections after compressed context
  - If corrections frequent → dial down to off
  - If no corrections → dial up to aggressive
  - Store profile, apply on next turn
- Show savings: "⚡ eco ↓45% (balanced mode for this project)"

### Pattern 7: Closed Loop Validation

**What Hermes Does:**
- Proposes improvements
- **Gates with strict validation** before adoption
- Prevents degradation

**Adapt for Claude Code:**
- When Claude suggests AINL workflow improvements:
  ```python
  def propose_improvement(current_ainl, suggestion):
      # Generate candidate
      candidate = apply_suggestion(current_ainl, suggestion)
      
      # Strict validate
      result = ainl_validate(candidate, strict=True)
      
      if result['valid']:
          # Show diff
          diff = unified_diff(current_ainl, candidate)
          return {
              'approved': True,
              'candidate': candidate,
              'diff': diff,
              'improvement': calculate_improvement(current_ainl, candidate)
          }
      else:
          return {
              'approved': False,
              'error': result['diagnostics'],
              'suggestion': 'Fix validation errors first'
          }
  ```
- User confirms before applying
- Track improvement success rate
- Adjust suggestion confidence based on history

### Pattern 8: Episodic Tool Sequence Learning

**What ArmaraOS Does:**
- Records every tool call in Episode nodes
- Extracts sequences that work together
- Suggests sequences for similar tasks

**Adapt for Claude Code:**
- After user completes task successfully:
  - Extract tool sequence from session
  - Example: Read → Grep → Edit → Write → Bash(test)
  - Store as episodic memory
  - Tag with task type (refactor/debug/test/etc)
- When user starts similar task:
  - Recall matching episodes
  - Suggest tool sequence: "When refactoring, you typically: read file → grep for pattern → edit in-place → test. Want me to follow that?"

### Pattern 9: Multi-Turn Context Compilation

**What ArmaraOS Does:**
- Compiles memory blocks: RecentAttempts, KnownFacts, KnownConflicts, SuggestedProcedure
- Ranked retrieval with strict caps
- Fail-closed (skip low-quality)

**Adapt for Claude Code:**
- Before each AINL-related turn:
  ```python
  def compile_ainl_context():
      context = []
      
      # Recent AINL executions (last 3 this session)
      recent = get_recent_ainl_episodes(limit=3)
      if recent:
          context.append(f"[Recent AINL Activity]\n{format_episodes(recent)}")
      
      # Known facts (top 5 by confidence × recurrence)
      facts = get_ranked_facts(min_confidence=0.5, limit=5)
      if facts:
          context.append(f"[Known AINL Patterns]\n{format_facts(facts)}")
      
      # Suggested patterns (fitness > 0.6, top 3)
      patterns = get_suggested_patterns(min_fitness=0.6, limit=3)
      if patterns:
          context.append(f"[Reusable Patterns]\n{format_patterns(patterns)}")
      
      # Active persona traits (strength > 0.6)
      traits = get_active_traits(min_strength=0.6)
      if traits:
          context.append(f"[User Preferences]\n{format_traits(traits)}")
      
      return "\n\n".join(context)
  ```
- Inject before Claude responds to AINL tasks
- Cap total context ~500 tokens
- Apply compression if over budget

### Pattern 10: Background Consolidation

**What ArmaraOS Does:**
- Background consolidation pass removes duplicate semantic rows
- Preserves highest-confidence row
- Rate-limited per agent

**Adapt for Claude Code:**
- Spawn background task after AINL pattern storage:
  ```python
  async def consolidate_patterns():
      # Find duplicate patterns (same adapters, similar source)
      dupes = find_duplicate_patterns()
      
      for group in dupes:
          # Keep highest fitness
          best = max(group, key=lambda p: p.fitness_score)
          
          # Merge metadata
          best.uses = sum(p.uses for p in group)
          best.successes = sum(p.successes for p in group)
          best.failures = sum(p.failures for p in group)
          best.fitness_score = calculate_fitness(best)
          
          # Delete others
          delete_patterns([p for p in group if p != best])
  ```
- Run max once per hour per project
- Prevents pattern table bloat

---

## Part 4: Implementation Roadmap

### Phase 1: Foundation (Week 1)

**Goal:** Set up trajectory capture and basic pattern storage.

**Tasks:**
1. Create `trajectory_capture.py`
   - Hook into AINL execution (run/compile)
   - Log to `ainl_trajectories.db`
   - Schema: id, session_id, source_hash, outcome, steps, tags
2. Enhance `ainl_patterns.py`
   - Add `recurrence_count`, `last_seen` columns
   - Implement FTS5 search by tags
   - Add recurrence tracking on pattern match
3. Test pattern recall on similar prompts

### Phase 2: Persona Evolution (Week 2)

**Goal:** Implement zero-LLM persona learning.

**Tasks:**
1. Create `persona_axes.py`
   - Define 5 axes (Instrumentality, Curiosity, Persistence, Systematicity, Verbosity)
   - Implement EMA update logic
   - Signal extraction from user actions
2. Add `persona_nodes` table
   - Schema: id, axis_name, strength, evolution_cycle, last_updated
   - Store axis evolution snapshot
3. Hook into AINL detection
   - When user creates AINL workflow → curiosity signal
   - When user validates → systematicity signal
   - When user runs immediately → instrumentality signal
4. Inject persona traits into Claude context
   - Format: `[User Persona: curiosity=0.72, systematicity=0.85]`
   - Only traits with strength > 0.6
5. Test persona evolution over 10+ interactions

### Phase 3: Smart Suggestions (Week 3)

**Goal:** Proactive pattern suggestions and failure prevention.

**Tasks:**
1. Implement semantic fact ranking
   - Rank by confidence × recurrence × recency
   - Inject top 5 facts into AINL context
2. Create failure resolution learning
   - Store failures with context
   - Store resolutions when fixed
   - Suggest resolutions on similar errors
3. Episodic tool sequence learning
   - Extract successful tool sequences
   - Tag by task type (refactor/debug/test)
   - Suggest sequences for similar tasks
4. Test suggestion accuracy (>60% acceptance rate)

### Phase 4: Adaptive Compression (Week 4)

**Goal:** Learn optimal compression settings per project.

**Tasks:**
1. Create `compression_profiles.py`
   - Track per-project compression stats
   - Auto-tune based on user corrections
   - Store optimal mode
2. Integrate with existing eco mode
   - Start with balanced
   - Adjust based on feedback
   - Show savings in context
3. Test compression quality preservation

### Phase 5: Closed Loop Validation (Week 5)

**Goal:** Safe improvement proposals with strict validation.

**Tasks:**
1. Implement improvement proposal system
   - Generate candidate AINL
   - Strict validate before showing user
   - Show diff and improvements
2. Track proposal success rate
   - Adjust confidence based on history
   - Learn what improvements work
3. Background consolidation
   - Merge duplicate patterns
   - Rate-limit per project
   - Prevent bloat

### Phase 6: Context Compilation (Week 6)

**Goal:** Intelligent multi-turn context assembly.

**Tasks:**
1. Implement memory block compilation
   - RecentAttempts (last 3 AINL executions)
   - KnownFacts (top 5 semantic facts)
   - SuggestedPatterns (fitness > 0.6, top 3)
   - ActiveTraits (strength > 0.6)
2. Context budget management
   - Cap at ~500 tokens
   - Apply compression if over
   - Fail-closed on low-quality
3. Test context quality (user satisfaction survey)

---

## Part 5: Success Metrics

### Engagement Metrics

- **Pattern Reuse Rate:** % of AINL workflows using recalled patterns (target: >40%)
- **Persona Accuracy:** User confirmation of persona traits (target: >70%)
- **Suggestion Acceptance:** % of suggestions accepted (target: >50%)

### Learning Quality Metrics

- **Failure Prevention:** % of similar errors prevented by resolution recall (target: >60%)
- **Pattern Fitness:** Average fitness score of promoted patterns (target: >0.7)
- **Recurrence Accuracy:** % of recalled facts marked relevant (target: >75%)

### Performance Metrics

- **Trajectory Capture Latency:** <50ms per execution
- **Pattern Recall Latency:** <100ms per query
- **Background Consolidation:** <30s per pass
- **Context Compilation:** <200ms per turn

### User Value Metrics

- **Token Savings:** Average compression savings (target: >40%)
- **Time Savings:** Reduced workflow creation time via patterns (target: >30%)
- **Error Reduction:** Fewer validation failures via learning (target: >50%)

---

## Part 6: Architecture Diagram

```
┌────────────────────────────────────────────────────────────────┐
│                    Claude Code Session                          │
└──────────────────┬─────────────────────────────────────────────┘
                   │
    ┌──────────────┼──────────────┐
    │              │              │
┌───▼────┐   ┌─────▼─────┐   ┌───▼────┐
│ Hooks  │   │   AINL    │   │Pattern │
│ System │◄─►│   Tools   │◄─►│ Memory │
│        │   │  (MCP)    │   │        │
└────────┘   └─────┬─────┘   └───┬────┘
                   │              │
            ┌──────▼──────────────▼────┐
            │  Trajectory Capture       │
            │  (JSONL execution logs)   │
            └──────┬────────────────────┘
                   │
    ┌──────────────┼──────────────┐
    │              │              │
┌───▼────┐   ┌─────▼─────┐   ┌───▼────┐
│Episode │   │ Semantic  │   │Persona │
│ Nodes  │   │  Fact     │   │  Axes  │
│        │   │Recurrence │   │  EMA   │
└───┬────┘   └─────┬─────┘   └───┬────┘
    │              │              │
    └──────────────▼──────────────┘
            ┌──────────────┐
            │   SQLite     │
            │ Graph Store  │
            └──────┬───────┘
                   │
    ┌──────────────┼──────────────┐
    │              │              │
┌───▼────┐   ┌─────▼─────┐   ┌───▼────┐
│Context │   │  Pattern  │   │Failure │
│Compile │   │ Promotion │   │Learning│
│        │   │           │   │        │
└────────┘   └───────────┘   └────────┘
```

---

## Conclusion

**Key Takeaways:**

1. **Graph-as-Memory** is the foundational paradigm - execution history becomes queryable knowledge
2. **Zero-LLM Learning** via persona axes and semantic signals reduces costs while improving
3. **Closed Loop Validation** ensures learning doesn't degrade quality
4. **Trajectory Capture** provides rich data for pattern extraction
5. **Adaptive Compression** balances context richness with token efficiency

**Integration Strategy:**

Start with Pattern 1 (Trajectory Capture) and Pattern 2 (Pattern Promotion) in Phase 1. These provide immediate value and lay the groundwork for more advanced patterns.

Build up to zero-LLM persona evolution (Pattern 3) in Phase 2, as this is the "magic" that makes the system learn without constant LLM introspection.

Close the loop with validation gates (Pattern 7) to ensure learning never degrades quality.

**Expected Outcome:**

A Claude Code plugin that:
- Learns from every AINL interaction
- Suggests patterns proactively
- Evolves user understanding without LLM overhead
- Prevents repeated mistakes
- Gets smarter over time, silently

This brings the best of Hermes' closed learning loop and ArmaraOS' graph-native architecture into Claude Code's AINL plugin.
