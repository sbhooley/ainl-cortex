# AINL Language Guide for Claude Code

**Purpose:** This document teaches Claude Code about AI Native Lang (AINL) so it can understand, suggest, and help users write AINL programs.

**Version:** 1.0 (AINL 1.7.0+)  
**Audience:** Claude Code AI

---

## What is AINL?

AINL (AI Native Lang) is a **graph-canonical, agent-native programming language** designed specifically for AI agents to write deterministic, multi-step workflows.

### Key Characteristics

- **Graph-native IR**: Compiles to deterministic intermediate representation
- **Token efficient**: 90-95% token savings for recurring workflows (compile once, run many times)
- **Adapter-based**: 50+ adapters for databases, APIs, LLMs, blockchain, etc.
- **Two syntaxes**: Compact (Python-like, recommended) and Opcode (low-level)
- **Effect-typed**: Pure vs IO operations are tracked
- **Verifiable**: Strict validation mode catches errors at compile time

### Design Philosophy

> **AINL is AI-to-AI.** Humans describe what they want in natural language. AI agents compile that into AINL. Humans review through tests, diffs, and runtime behavior—not AINL source.

**However**, for Claude Code integration, we help users understand and write AINL directly when beneficial.

---

## When to Suggest AINL

### ✅ STRONG Recommendations (Suggest Proactively)

Suggest .ainl files when users request:

1. **Recurring workflows, monitors, scheduled jobs**
   - "Check X every hour"
   - "Monitor Y daily"
   - "Run Z at midnight"
   - **Token savings: 90-95%** vs re-generating Python each run

2. **Multi-step automations with external APIs**
   - "Fetch from API A, process, send to API B"
   - "Check status, if X then do Y, else Z"
   - **Benefit: Deterministic graph execution**

3. **Blockchain interactions**
   - "Check Solana balance and alert if low"
   - "Transfer tokens when condition met"
   - **Benefit: Specialized adapters (Solana, etc.)**

4. **Cost-sensitive operations**
   - User mentions "token costs", "expensive", "budget"
   - Operations that repeat frequently
   - **Benefit: Compile once, run many times**

5. **AI agent workflows**
   - Multi-step LLM orchestration
   - Tool calling sequences
   - **Benefit: Graph-native design for agent coordination**

6. **Data processing pipelines**
   - ETL workflows
   - Data transformation sequences
   - **Benefit: Explicit dataflow, type checking**

### ⚠️ CONDITIONAL Recommendations (Suggest with Caveats)

Consider suggesting .ainl for:

- **API endpoints** → Can emit to FastAPI, but TypeScript/Python may be better for complex logic
- **Scheduled tasks** → Great for AINL, but one-off scripts better in Python
- **Simple automations** → AINL if recurring, Python if one-time

### ❌ DON'T Suggest AINL For

1. **One-off scripts** → Use Python/TS (no cost benefit)
2. **Complex web UIs** → Use React/TypeScript
3. **ML training scripts** → Use Python
4. **Real-time dashboards** → Use React/TS
5. **Interactive applications** → Not AINL's purpose
6. **Large dataset iteration** → Python recursion limit issues (>20 records)

---

## AINL Syntax: Two Formats

### Compact Syntax (RECOMMENDED)

Python-like, human-friendly. Use for new code.

**Basic structure:**
```ainl
# name: creates a label/workflow
# name @cron "schedule": creates scheduled job
# name @api "/path": creates API endpoint

workflow_name:
  # in: declares input fields
  in: field1 field2
  
  # Assignment: var = adapter.op args
  result = http.GET "https://api.example.com/data"
  
  # Condition: if expr:
  if result.status == 200:
    data = core.GET result "data"
    out data
  
  # Return: out expr
  out {error: "failed"}
```

**Complete example:**
```ainl
# Monitor Solana balance hourly
balance_checker @cron "0 * * * *":
  balance = solana.GET_BALANCE "WalletAddress"
  lamports = core.GET balance "lamports"
  
  if lamports < 500000000:
    http.POST $SLACK_WEBHOOK {text: "Low balance!"}
    out {alert: "sent", lamports: lamports}
  
  out {status: "ok", lamports: lamports}
```

### Opcode Syntax (LOW-LEVEL)

1-character opcodes for power users. More verbose.

**Basic structure:**
```ainl
S <service> <mode> <path>    # Service declaration
D <type> <field:type>...     # Data type definition
L<n>:                        # Label (workflow node)
  R <adapter.op> <args> ->var  # Request: call adapter
  If <cond> ->L1 ->L2        # Conditional branch
  J <var>                    # Join: return value
```

**Same example in opcode:**
```ainl
S app core noop

L1:
  R solana.GET_BALANCE "WalletAddress" ->balance
  X lamports get balance lamports
  X threshold 500000000
  X is_low (core.lt lamports threshold)
  If is_low ->L_alert ->L_ok

L_alert:
  R http.POST $SLACK_WEBHOOK {"text":"Low balance!"} ->resp
  Set status "alert_sent"
  J status

L_ok:
  Set status "ok"
  J status
```

**For Claude Code:** Prefer generating **compact syntax** for users. It's more readable and maintainable.

---

## Common Patterns Library

### Pattern 1: Simple API Call

```ainl
# Compact
fetch_data:
  in: user_id
  result = http.GET "https://api.example.com/users/${user_id}"
  out result
```

### Pattern 2: Conditional Logic

```ainl
# Compact
classify_severity:
  in: level message
  
  if level == "CRITICAL":
    out {priority: "high", action: "page_oncall"}
  
  if level == "WARNING":
    out {priority: "medium", action: "log"}
  
  out {priority: "low", action: "ignore"}
```

### Pattern 3: Monitor Pattern (Most Common)

```ainl
# Monitor with alert
resource_monitor @cron "*/15 * * * *":  # Every 15 minutes
  status = http.GET "https://api.service.com/health"
  health = core.GET status "status"
  
  if health != "healthy":
    http.POST $ALERT_WEBHOOK {
      text: "Service unhealthy: ${health}"
    }
    out {alerted: true, status: health}
  
  out {ok: true, status: health}
```

### Pattern 4: Data Pipeline

```ainl
# ETL pipeline
process_records:
  in: source_url
  
  # Extract
  raw = http.GET source_url
  records = core.GET raw "records"
  
  # Transform (using core ops)
  count = core.LEN records
  
  # Load
  http.POST "https://warehouse.example.com/ingest" {
    count: count,
    records: records
  }
  
  out {processed: count}
```

### Pattern 5: Multi-Step Automation

```ainl
# Approval workflow
approval_flow:
  in: request_id
  
  # Step 1: Fetch request
  request = http.GET "https://api.example.com/requests/${request_id}"
  amount = core.GET request "amount"
  
  # Step 2: Check threshold
  if amount > 10000:
    # High value - require manual approval
    http.POST $APPROVAL_WEBHOOK {request_id: request_id}
    out {status: "pending_approval"}
  
  # Step 3: Auto-approve low amounts
  http.POST "https://api.example.com/approve" {
    request_id: request_id,
    auto_approved: true
  }
  
  out {status: "approved"}
```

### Pattern 6: Blockchain Monitor

```ainl
# Solana balance monitor
wallet_monitor @cron "0 * * * *":
  in: wallet_address threshold_sol
  
  balance = solana.GET_BALANCE wallet_address
  lamports = core.GET balance "lamports"
  
  # Convert lamports to SOL (1 SOL = 1B lamports)
  threshold_lamports = core.MUL threshold_sol 1000000000
  
  if lamports < threshold_lamports:
    http.POST $SLACK_WEBHOOK {
      text: "Wallet ${wallet_address} below ${threshold_sol} SOL"
    }
    out {alert: true, balance_sol: lamports}
  
  out {ok: true, balance_sol: lamports}
```

### Pattern 7: LLM Workflow

```ainl
# AI agent workflow with LLM
content_moderator:
  in: content
  
  # Classify content
  classification = llm.completion "Is this content safe? Reply YES or NO: ${content}"
  is_safe = core.EQ classification "YES"
  
  if is_safe:
    out {approved: true, content: content}
  
  # Flag for review
  http.POST "https://api.example.com/flag" {
    content: content,
    reason: "ai_flagged"
  }
  
  out {approved: false, flagged: true}
```

---

## Available Adapters

### Core Adapters (Always Available)

**`core`** - Built-in operations
- Arithmetic: `ADD`, `SUB`, `MUL`, `DIV`, `IDIV`
- Comparison: `EQ`, `NEQ`, `GT`, `LT`, `GTE`, `LTE`
- String: `CONCAT`, `SPLIT`, `LOWER`, `UPPER`, `TRIM`, `REPLACE`
- Data: `GET`, `PARSE`, `STRINGIFY`, `MERGE`, `LEN`
- Array/Object: `KEYS`, `VALUES`
- Type: `STR`, `INT`, `FLOAT`, `BOOL`
- Time: `NOW`, `ISO`, `ISO_TS`
- Misc: `ECHO`, `ENV`, `SUBSTR`, `SLEEP`

### Network Adapters

**`http`** - HTTP requests
- `GET`, `POST`, `PUT`, `DELETE`, `PATCH`
- Syntax: `R http.GET url [headers] [timeout_s] ->result`

**`web`** - Web search/scraping (OpenClaw)
- `SEARCH`, `FETCH`, `SCRAPE`, `GET`

### Blockchain Adapters

**`solana`** - Solana RPC (1447 lines)
- `GET_BALANCE`, `TRANSFER`, `GET_TRANSACTION`, etc.

### Database Adapters

- **`postgres`** - PostgreSQL queries
- **`mysql`** - MySQL queries  
- **`sqlite`** - SQLite operations
- **`redis`** - Redis get/set/pub/sub
- **`dynamodb`** - AWS DynamoDB
- **`supabase`** - Supabase client
- **`airtable`** - Airtable API

### AI/LLM Adapters

**`llm/*`** - LLM providers (requires config)
- `llm.openrouter` - OpenRouter
- `llm.ollama` - Local Ollama
- `llm.anthropic` - Claude
- `llm.cohere` - Cohere

Operations: `completion`, `chat`, `embed`

### Memory Adapters

**`memory`** - Key-value store with patterns
- `get`, `set`, `delete`
- `store_pattern`, `recall_pattern`

**`ainl_graph_memory`** - ArmaraOS graph store
- `search`, `recall`, `merge`, `update`
- IR ops: `MemoryRecall`, `MemorySearch`

**`cache`** - Simple cache
- `get`, `set`, `delete`

**`queue`** - Message queue
- `put`, `get`

### Service Adapters

**`svc`** - Service control (OpenClaw)
- `STATUS`, `RESTART`, `CADDY`, `NGINX`, `HEALTH`

**`crm`** - CRM operations (OpenClaw)
- `QUERY`, `UPDATE`

**`tiktok`** - TikTok data (OpenClaw)
- `RECENT`, `SEARCH`, `PROFILE`, `STATS`, `TRENDING`

### Check Available Adapters

Use the MCP tool `ainl_capabilities` to see what's available in the current environment.

---

## Critical Syntax Rules

### 1. HTTP Adapter Arguments (CRITICAL)

**❌ WRONG:**
```ainl
# Don't use named arguments like params= or timeout=
result = http.GET url params={x: 1} timeout=30
```

**✅ CORRECT:**
```ainl
# Positional arguments only:
# 1. URL (with query string)
# 2. Headers dict (optional)
# 3. Timeout in seconds (optional)

result = http.GET "https://api.example.com/data?x=1" {} 30
```

**Query parameters go IN the URL:**
```ainl
# Good
result = http.GET "https://api.example.com/users?id=123&type=active"

# Good with timeout
result = http.GET "https://api.example.com/data" {} 15

# Good with headers
result = http.GET "https://api.example.com/api" {Authorization: "Bearer token"} 30
```

### 2. Dict Literals Don't Work in R Lines (CRITICAL)

**❌ WRONG:**
```ainl
# Inline dict literals are parsed as strings, not dicts
result = http.POST url {key: "value"}
```

**✅ CORRECT:**
```ainl
# Option 1: Pass via frame (in ainl_run call)
# frame: {"body": {"key": "value"}}
result = http.POST url body

# Option 2: Build with core ops
data = core.PARSE '{"key": "value"}'
result = http.POST url data
```

### 3. core.GET Argument Order

**❌ WRONG:**
```ainl
value = core.GET "key" object  # Key first
```

**✅ CORRECT:**
```ainl
value = core.GET object "key"  # Object first, then key
```

### 4. Variable Shadowing (IMPORTANT)

String literals in R args are resolved against the frame:

```ainl
# If frame has variable named "records"
records = http.GET "https://api.com/data"

# This will use the LIST, not the string "records"!
field = core.GET data "records"

# Solution: Use unique prefixes
fetch_records = http.GET "https://api.com/data"
field = core.GET data "records"  # Now "records" is a string
```

### 5. Frame Hints for ainl_run

Add comments to specify required inputs:

```ainl
# frame: api_key: string
# frame: user_id: number
# frame: webhook_url: string

fetch_user:
  in: user_id
  result = http.GET "https://api.example.com/users/${user_id}" {
    Authorization: "Bearer ${api_key}"
  }
  out result
```

The `ainl_compile` tool will extract these as `frame_hints`.

---

## Error Patterns and Fixes

### Error: "unknown adapter"

**Symptom:**
```
Error: unknown adapter 'httP' (did you mean 'http'?)
```

**Fix:**
- Check spelling (case-sensitive)
- Run `ainl_capabilities` to see available adapters
- Common typo: `httP` → `http`

### Error: "could not convert string to float: '='"

**Symptom:**
```
Error in http.GET: could not convert string to float: '='
```

**Cause:** Using named arguments like `params=` or `timeout=`

**Fix:** Use positional arguments only
```ainl
# Wrong
result = http.GET url params={x:1} timeout=15

# Right
result = http.GET url {} 15
```

### Error: "unknown X fn: {"

**Symptom:**
```
Error: unknown X fn: {
```

**Cause:** Inline dict literal in compact syntax

**Fix:** Pass dict via frame or build with core ops
```ainl
# Wrong
data = {key: "value"}

# Right
data = core.PARSE '{"key": "value"}'
```

### Error: "max_adapter_calls exceeded"

**Symptom:**
```
Runtime error: max_adapter_calls limit reached
```

**Cause:** Too many adapter calls (default limit: 50,000)

**Fix:**
- Optimize workflow to reduce calls
- Increase limit in `ainl_run` call: `limits: {max_adapter_calls: 100000}`
- Check for infinite loops

### Error: "recursion limit"

**Symptom:**
```
RecursionError: maximum recursion depth exceeded
```

**Cause:** Tail-recursive loops over large datasets

**Fix:** AINL is not suited for >20 records via recursion. Use Python script or batch processing.

---

## Workflow: Validate → Compile → Run

### Step 1: Validate (Always First)

```javascript
// MCP call
ainl_validate({
  source: "...",
  strict: true
})

// Returns:
{
  valid: true/false,
  diagnostics: [...],
  primary_diagnostic: {...},
  agent_repair_steps: [...],
  recommended_next_tools: [...]
}
```

### Step 2: Compile (Get IR + Frame Hints)

```javascript
ainl_compile({
  source: "...",
  strict: true
})

// Returns:
{
  ok: true,
  ir: {...},
  frame_hints: [
    {name: "api_key", type: "string", source: "comment"}
  ]
}
```

### Step 3: Run (Execute)

```javascript
ainl_run({
  source: "...",
  frame: {
    api_key: "sk-...",
    user_id: 123
  },
  adapters: {
    enable: ["http", "cache"],
    http: {
      allow_hosts: ["api.example.com"],
      timeout_s: 30
    },
    cache: {
      path: "/path/to/cache.json"
    }
  },
  limits: {
    max_steps: 500000,
    max_adapter_calls: 50000,
    max_time_ms: 900000
  }
})

// Returns:
{
  ok: true,
  result: {...},
  stats: {
    steps_executed: 42,
    adapter_calls: 7
  }
}
```

---

## Token Savings Calculation

### Example: Hourly Monitor

**Python approach (traditional):**
```
User: "Check API health every hour"
→ Generate Python script: 500 tokens
→ Run 24x/day: 500 × 24 = 12,000 tokens/day
→ Monthly: 360,000 tokens
→ Cost at $10/1M: $3.60/month
```

**AINL approach:**
```
User: "Check API health every hour"
→ Generate .ainl: 200 tokens (once)
→ Compile to IR: 50 tokens (once)
→ Run 24x/day: ~5 tokens × 24 = 120 tokens/day
→ Monthly: 3,600 tokens
→ Cost at $10/1M: $0.04/month
```

**Savings: 99% reduction** 🎉

### When to Explain This

Mention token savings when:
- User asks about costs
- Workflow will run repeatedly
- User is cost-conscious
- Comparing AINL vs Python for a task

---

## Suggesting AINL: Best Practices

### 1. Detect Opportunity

Look for keywords:
- "every", "hourly", "daily", "monitor", "check", "workflow", "automation"
- "recurring", "scheduled", "cron"
- "if...then", "when X happens"
- "expensive", "costs", "budget"

### 2. Suggest Proactively

```markdown
I'll create this as an AINL workflow - this will save ~95% on token costs 
for hourly execution!

[Show AINL code]

This compiles once (~200 tokens) then runs hourly at ~5 tokens per execution,
compared to ~500 tokens each time if generated fresh in Python.
```

### 3. Explain Trade-offs

```markdown
For a one-time script, Python would be simpler. But since this runs hourly,
AINL will save significant costs:

- First run: ~250 tokens (compile + execute)  
- Subsequent runs: ~5 tokens each
- Monthly savings: ~$3.50 at current pricing

Would you like me to create this in AINL?
```

### 4. Validate Before Claiming Success

Always run `ainl_validate` before telling the user the code is ready.

### 5. Provide Next Steps

```markdown
Created `monitor.ainl`. Next steps:

1. Test: `ainl run monitor.ainl`
2. Schedule: Add to cron or ArmaraOS
3. Monitor: Check logs for execution

The workflow is ready to run!
```

---

## Integration with Graph Memory

When working with AINL:

1. **Store successful patterns** in graph memory (Procedural type)
2. **Track fitness scores** (success/failure ratio)
3. **Recall similar patterns** when users ask for similar workflows
4. **Extract reusable components** from successful AINL programs

Example pattern extraction:
```python
# In pattern memory
{
  "pattern_type": "api_monitor",
  "ainl_template": "...",
  "fitness_score": 0.95,
  "uses": ["http.GET", "if condition", "alert webhook"],
  "description": "Check API endpoint, alert if down"
}
```

---

## Resources to Reference

When helping users with AINL:

1. **MCP Resources:**
   - `ainl://authoring-cheatsheet` - Quick reference
   - `ainl://adapter-manifest` - Full adapter list
   - `ainl://security-profiles` - Security guidance

2. **MCP Tools:**
   - `ainl_capabilities` - Current adapter list
   - `ainl_validate` - Check syntax
   - `ainl_compile` - Get IR
   - `ainl_run` - Execute
   - `ainl_security_report` - Security analysis

3. **Documentation:**
   - Local templates: `~/.claude/plugins/ainl-cortex/templates/ainl/`
   - Examples: Show from template library

---

## Summary Checklist

When working with AINL, Claude Code should:

✅ **Recognize opportunities** - Detect when AINL is beneficial  
✅ **Suggest proactively** - Recommend .ainl for recurring workflows  
✅ **Explain benefits** - Token savings, deterministic execution  
✅ **Validate first** - Always run `ainl_validate --strict`  
✅ **Use compact syntax** - More readable for users  
✅ **Avoid common errors** - No `params=`, dict via frame, etc.  
✅ **Provide frame hints** - Add `# frame:` comments  
✅ **Test before claiming success** - Run validation  
✅ **Store patterns** - Save successful workflows to graph memory  
✅ **Recall similar work** - Reference past AINL patterns  

---

**Last Updated:** 2026-04-21  
**AINL Version:** 1.7.0+  
**Package:** `ainativelang[mcp]` from PyPI
