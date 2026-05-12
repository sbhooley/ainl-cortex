# AINL User Guide for Claude Code

**AI Native Lang (AINL)** is now integrated into Claude Code through **AINL Cortex**!

This guide shows you how to use AINL to create cost-efficient, deterministic workflows.

---

## What is AINL?

AINL is a **graph-based programming language** designed for AI workflows:

- **Compile once, run many times** - 90-95% token savings for recurring tasks
- **Deterministic execution** - Same input always produces same output
- **50+ adapters** - Databases, APIs, blockchains, LLMs, and more
- **Graph-native** - Natural representation of multi-step workflows

### When Should I Use AINL?

✅ **Great for AINL:**
- Hourly/daily monitors and checks
- Recurring workflows and automations
- Blockchain interactions (Solana, etc.)
- Multi-step API workflows
- Cost-sensitive operations

❌ **Better in Python/TS:**
- One-off scripts
- Complex web UIs
- ML training
- Interactive applications

---

## Getting Started

### 1. Claude Will Suggest AINL

When you describe a recurring workflow, Claude will proactively suggest using AINL:

**You:**
> "Create a script that checks my Solana wallet balance every hour and alerts me on Slack if it's below 1 SOL"

**Claude:**
> I recommend creating this as an AINL workflow (.ainl file).
> 
> Why AINL for monitoring:
> - Built-in cron scheduling  
> - Compile once, run repeatedly
> - 90-95% token savings
>
> This compiles once (~200 tokens) then runs hourly at ~5 tokens per execution.
>
> Would you like me to create a .ainl monitor for this?

### 2. Claude Creates the Workflow

Claude will generate a `.ainl` file:

```ainl
# wallet_monitor.ainl
# frame: wallet_address: string
# frame: alert_webhook: string

wallet_monitor @cron "0 * * * *":  # Every hour
  balance = solana.GET_BALANCE wallet_address
  lamports = core.GET balance "lamports"
  
  # Check if below 1 SOL (1B lamports)
  threshold = 1000000000
  is_low = core.LT lamports threshold
  
  if is_low:
    current_sol = core.DIV lamports 1000000000
    http.POST alert_webhook {
      text: "💰 Low balance: ${current_sol} SOL"
    }
    out {alerted: true, balance_sol: current_sol}
  
  out {ok: true, balance_sol: current_sol}
```

### 3. Claude Validates Automatically

After creating the file, Claude automatically validates it:

```
✅ AINL Validation: wallet_monitor.ainl

Validation successful

Next steps: ainl_compile, ainl_capabilities, ainl_run
```

If there are errors, Claude will show diagnostics and suggest fixes.

---

## AINL Syntax Basics

### Compact Syntax (Recommended)

AINL uses Python-like syntax:

```ainl
# Workflow definition
workflow_name:
  # Input parameters
  in: param1 param2
  
  # Call adapter (fetch data, compute, etc.)
  result = adapter.operation argument1 argument2
  
  # Conditional logic
  if condition:
    # then branch
  
  # Return value
  out {result: value}
```

### Common Operations

**HTTP request:**
```ainl
response = http.GET "https://api.example.com/data" {} 30
```

**Get field from object:**
```ainl
value = core.GET object "field_name"
```

**Math:**
```ainl
sum = core.ADD 2 3
product = core.MUL sum 5
```

**Conditions:**
```ainl
if value > 100:
  # do something
```

**Schedule (cron):**
```ainl
daily_task @cron "0 2 * * *":  # Daily at 2 AM
  # workflow steps
```

---

## Working with AINL Files

### Creating a Workflow

**Option 1: Ask Claude**

```
"Create an AINL workflow that checks https://api.example.com/health 
every 5 minutes and alerts me if it's down"
```

Claude will generate the `.ainl` file.

**Option 2: Use a Template**

Templates are in `~/.claude/plugins/ainl-graph-memory/templates/ainl/`:

```bash
# Copy template
cp ~/.claude/plugins/ainl-graph-memory/templates/ainl/monitor_workflow.ainl my_monitor.ainl

# Edit it
# Then ask Claude to validate
```

**You:**
> "Validate my_monitor.ainl"

### Editing Workflows

When you edit a `.ainl` file (using Read, Edit, or Write), Claude automatically validates it and shows you any errors:

```
❌ AINL Validation: my_workflow.ainl

Error: unknown adapter 'httP' (did you mean 'http'?)
Line: 5

How to fix:
- Run ainl_capabilities to see available adapters
- Check adapter spelling (case-sensitive)
```

### Frame Variables

Workflows need **frame variables** for runtime values (API keys, URLs, etc.):

```ainl
# Declare frame variables in comments
# frame: api_key: string
# frame: webhook_url: string

my_workflow:
  response = http.GET "https://api.example.com/data" {
    Authorization: "Bearer ${api_key}"
  }
  # ...
```

When running, you'll pass these as parameters.

---

## Common Patterns

### 1. API Monitor

Check an endpoint every N minutes:

```ainl
# frame: health_url: string
# frame: alert_webhook: string

health_check @cron "*/5 * * * *":  # Every 5 minutes
  response = http.GET health_url {} 10
  status = core.GET response "status"
  
  if status != "healthy":
    http.POST alert_webhook {
      text: "Service down: ${status}"
    }
    out {alerted: true}
  
  out {ok: true}
```

### 2. Data Pipeline

Fetch, transform, load:

```ainl
# frame: source_api: string
# frame: warehouse_url: string

daily_export @cron "0 2 * * *":  # 2 AM daily
  # Extract
  data = http.GET source_api
  records = core.GET data "records"
  
  # Transform (example: count)
  count = core.LEN records
  
  # Load
  http.POST warehouse_url {
    date: core.ISO,
    count: count,
    records: records
  }
  
  out {processed: count}
```

### 3. Conditional Workflow

Multi-step with branching:

```ainl
# frame: request_id: string
# frame: api_url: string

approval_flow:
  in: request_id
  
  # Fetch request
  request = http.GET "${api_url}/requests/${request_id}"
  amount = core.GET request "amount"
  
  # Auto-approve if under threshold
  if amount < 10000:
    http.POST "${api_url}/approve" {
      request_id: request_id,
      auto_approved: true
    }
    out {status: "approved"}
  
  # Needs manual approval
  out {status: "pending", amount: amount}
```

---

## Understanding Token Savings

### How AINL Saves Tokens

**Traditional approach (Python script):**
```
User: "Check API hourly"
→ Generate Python: 500 tokens
→ Run 24×/day: 500 × 24 = 12,000 tokens/day
```

**AINL approach:**
```
User: "Check API hourly"
→ Generate .ainl: 200 tokens (once)
→ Compile: 50 tokens (once)
→ Run 24×/day: 5 × 24 = 120 tokens/day
```

**Result: 99% reduction!**

### Real Example

**Scenario:** Check Solana balance hourly for a month

| Approach | Tokens/Month | Cost @ $10/1M | Savings |
|----------|--------------|---------------|---------|
| Python (regen each time) | 360,000 | $3.60 | — |
| AINL (compile once) | 3,600 | $0.04 | 99% |

### When Savings Apply

Token savings are most significant for:
- ✅ Hourly/daily monitors (running 100s of times)
- ✅ Recurring workflows (daily, weekly)  
- ✅ Scheduled automations
- ⚠️ One-time tasks (minimal savings - overhead of compilation)

---

## Available Adapters

Ask Claude: "Show me available AINL adapters" or use the MCP tool.

### Most Common:

**core** - Built-in operations (always available)
- Math: `ADD`, `SUB`, `MUL`, `DIV`
- String: `CONCAT`, `TRIM`, `SPLIT`
- Data: `GET`, `PARSE`, `STRINGIFY`, `LEN`
- Type: `STR`, `INT`, `FLOAT`, `BOOL`
- Time: `NOW`, `ISO`

**http** - HTTP requests
- `GET`, `POST`, `PUT`, `DELETE`

**solana** - Solana blockchain
- `GET_BALANCE`, `TRANSFER`, etc.

**sqlite** - SQLite database
- `QUERY`, `EXECUTE`

**llm** - LLM calls (requires config)
- `completion`, `chat`

### Full List

Run `ainl_capabilities` through Claude to see all 50+ adapters.

---

## Common Mistakes & Fixes

### ❌ Mistake 1: Named Arguments on HTTP

```ainl
# Wrong
response = http.GET url params={x:1} timeout=30
```

**Fix:** Use positional arguments
```ainl
# Right
response = http.GET "https://api.com/data?x=1" {} 30
```

### ❌ Mistake 2: Inline Dict Literals

```ainl
# Wrong
data = {key: "value"}
```

**Fix:** Pass via frame or use `core.PARSE`
```ainl
# Right (pass in frame)
# frame: data: object
# Then use: data

# Or build with core
data = core.PARSE '{"key": "value"}'
```

### ❌ Mistake 3: Wrong core.GET Order

```ainl
# Wrong
value = core.GET "key" object
```

**Fix:** Object first, then key
```ainl
# Right
value = core.GET object "key"
```

### ❌ Mistake 4: Typos in Adapter Names

```ainl
# Wrong (case-sensitive)
response = http.get url
response = HTTP.GET url
```

**Fix:** Exact case
```ainl
# Right
response = http.GET url
```

---

## FAQ

### Q: How do I run an AINL workflow?

**A:** Ask Claude! 

```
"Run wallet_monitor.ainl with my wallet address"
```

Claude will use the `ainl_run` MCP tool with appropriate parameters.

### Q: Can I see the compiled IR?

**A:** Yes, ask Claude:

```
"Compile my_workflow.ainl and show me the IR"
```

### Q: How do I schedule a workflow?

**A:** Add `@cron` schedule in the workflow:

```ainl
my_task @cron "0 * * * *":  # Hourly
  # workflow steps
```

Then deploy to a cron system or ArmaraOS.

### Q: What if I need a new adapter?

**A:** Check if it exists with `ainl_capabilities`. If not, you can:
1. Use the `http` adapter for API calls
2. Request it in the AINL repo
3. For now, use Python for unsupported integrations

### Q: Can AINL replace all my scripts?

**A:** Not all - use AINL for:
- Recurring workflows (great savings)
- Multi-step automations
- API workflows
- Blockchain interactions

Stick with Python/TS for:
- One-off scripts (no cost benefit)
- Complex UIs
- ML training

---

## Next Steps

1. **Try it!** Ask Claude to create an AINL workflow for something you do regularly

2. **Explore templates** in `~/.claude/plugins/ainl-graph-memory/templates/ainl/`

3. **Check the language guide** at `docs/AINL_LANGUAGE_GUIDE.md` for complete syntax reference

4. **Share patterns** - Successful workflows become reusable templates

---

## Support & Resources

- **Ask Claude:** "How do I... in AINL?"
- **MCP Tools:** `ainl_validate`, `ainl_compile`, `ainl_run`, `ainl_capabilities`
- **Templates:** `~/.claude/plugins/ainl-graph-memory/templates/ainl/`
- **Official docs:** https://ainativelang.com
- **Language spec:** https://github.com/sbhooley/ainativelang

---

**Happy workflow building!** 🚀

AINL + Claude Code = Massive token savings + Deterministic execution
