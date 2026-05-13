# AINL First-Class Language Integration - Executive Summary

## Overview

This integration makes **AI Native Lang (AINL)** a first-class programming language in Claude Code, enabling:

1. ✅ **Full AINL language understanding** - Claude knows syntax, patterns, best practices
2. ✅ **Smart suggestions** - Auto-suggest .ainl for workflows, monitors, automations
3. ✅ **All MCP tools** - Validate, compile, run, analyze AINL code
4. ✅ **Token savings awareness** - Explain 90-95% cost reduction for recurring tasks
5. ✅ **Pattern memory** - Store and recall successful AINL workflows

## Why AINL?

AINL is a **graph-canonical, agent-native language** designed specifically for AI to write deterministic workflows:

### Token Savings Example

**Traditional Python approach:**
```
User: "Monitor Solana balance hourly, alert if low"
→ Agent writes Python script: 500 tokens
→ Runs 24x/day: 500 × 24 = 12,000 tokens/day
→ Monthly cost: $3.60
```

**AINL approach:**
```
User: "Monitor Solana balance hourly, alert if low"
→ Agent writes .ainl: 200 tokens (ONCE)
→ Compiles to IR: 50 tokens
→ Runs 24x/day: 5 × 24 = 120 tokens/day
→ Monthly cost: $0.04
```

**Result: 99% cost reduction** 🎉

## Architecture

```
┌────────────────────────────────────────┐
│        Claude Code Session             │
└──────────────┬─────────────────────────┘
               │
    ┌──────────┼──────────┐
    │          │          │
┌───▼───┐  ┌───▼───┐  ┌──▼────┐
│ AINL  │  │ AINL  │  │ Graph │
│Context│◄─► MCP   │◄─►Memory │
│System │  │ Tools │  │       │
└───────┘  └───┬───┘  └───────┘
               │
        ┌──────▼──────┐
        │ AINL Engine │
        │ (compile +  │
        │  runtime)   │
        └─────────────┘
```

## Implementation Phases

### Phase 1: Core Integration (Week 1)

**Deliverables:**
- `docs/AINL_LANGUAGE_GUIDE.md` - Complete language reference for Claude
- `mcp_server/ainl_tools.py` - 14+ MCP tools (validate, compile, run, etc.)
- `CLAUDE.md` - Instructions for Claude Code

**MCP Tools:**
- `ainl_validate` - Syntax validation with --strict mode
- `ainl_compile` - Compile to IR JSON
- `ainl_run` - Execute workflows
- `ainl_capabilities` - List available adapters
- `ainl_security_report` - Security analysis
- `ainl_ir_diff` - Compare IR graphs
- `ainl_import_*` - Import from ecosystems

### Phase 2: Smart Suggestions (Week 2)

**Deliverables:**
- `hooks/ainl_detection.py` - Detect when to suggest AINL
- `mcp_server/ainl_context.py` - Context injection system

**Detection Triggers:**
- Keywords: "workflow", "automation", "monitor", "schedule", "recurring"
- Multi-step processes
- API integration requests
- Cost concerns
- .ainl files in workspace

### Phase 3: Advanced Features (Week 3)

**Deliverables:**
- `mcp_server/ainl_patterns.py` - Pattern memory system
- `hooks/ainl_validator.py` - Auto-validation on save
- `templates/ainl/` - Template library

**Pattern Memory:**
- Stores successful AINL workflows
- Recalls similar patterns
- Promotes reuse
- Tracks fitness scores

**Templates:**
- API endpoint
- Monitor workflow
- Data pipeline
- LLM workflow
- Blockchain client

### Phase 4: User Experience (Week 4)

**Deliverables:**
- `docs/USER_GUIDE_AINL.md` - User documentation
- `cli/ainl_onboard.py` - Interactive onboarding
- Examples and demos

## Key Features

### 1. Language Awareness

Claude understands:
- **Compact syntax** (Python-like) - Recommended
- **Opcode syntax** (low-level) - Power users
- **Common patterns** - API calls, data processing, monitoring
- **Error patterns** - How to fix common mistakes
- **Adapter ecosystem** - 50+ adapters available

### 2. Smart Suggestions

Claude suggests AINL when users need:
- ✅ Recurring workflows and monitors (90-95% savings)
- ✅ Multi-step automations
- ✅ Blockchain interactions
- ✅ AI agent workflows
- ✅ Cost-sensitive operations

Claude does NOT suggest AINL for:
- ❌ One-off scripts (use Python)
- ❌ Complex UIs (use React/TS)
- ❌ ML training (use Python)

### 3. Validation & Compilation

Workflow:
1. User writes .ainl code
2. Auto-validate on save (or manual trigger)
3. Show diagnostics inline
4. Suggest fixes using `agent_repair_steps`
5. Compile to IR
6. Run or emit to target platform

### 4. Pattern Memory

Graph memory integration:
- Extracts reusable patterns from successful workflows
- Stores in typed graph nodes (Procedural type)
- Recalls similar patterns for new tasks
- Tracks fitness scores (success/failure ratio)

### 5. Ecosystem Integration

Import from:
- **ClawFlow** templates
- **Agency Agents** workflows
- **Markdown** documentation
- **ArmaraOS** Hands (packaged agents)

## Use Case Matrix

| Use Case | Python/TS | AINL | Why |
|----------|-----------|------|-----|
| Recurring monitor | ❌ | ✅ | 90-95% token savings |
| API endpoint | ⚠️ | ✅ | Can emit to FastAPI |
| Blockchain client | ❌ | ✅ | Specialized adapters |
| Multi-step automation | ⚠️ | ✅ | Deterministic graphs |
| Scheduled job | ❌ | ✅ | Built-in cron support |
| AI agent workflow | ⚠️ | ✅ | Graph-native design |
| One-off script | ✅ | ❌ | No cost benefit |
| Complex UI | ✅ | ❌ | Not AINL's purpose |
| ML training | ✅ | ❌ | Better in Python |

## Available Adapters

AINL has 50+ adapters for:

**Data:**
- `postgres`, `mysql`, `redis`, `dynamodb`, `supabase`, `airtable`, `sqlite`

**AI:**
- `llm/*` (OpenRouter, Ollama, Anthropic, Cohere)
- `ainl_graph_memory` (ArmaraOS graph store)

**Web:**
- `http` (HTTP requests)
- `web` (Search, fetch, scrape)
- `tiktok` (TikTok data)

**Blockchain:**
- `solana` (Solana RPC - 1447 lines)
- `blockchain-client` emitter

**Utilities:**
- `core` (Built-in ops: ADD, SUB, GET, LEN, MAP, etc.)
- `cache` (Key-value cache)
- `queue` (Message queues)
- `svc` (Service control)
- `crm` (CRM operations)
- `memory` (Pattern storage)

## Example: Simple Monitor in AINL

**Compact syntax:**
```ainl
# monitor_balance.ainl
balance_checker @cron "0 * * * *":  # Every hour
  balance = solana.GET_BALANCE "YourWalletAddress"
  lamports = core.GET balance "lamports"
  
  if lamports < 500000000:
    status = http.POST $SLACK_WEBHOOK {
      text: "Low balance alert!"
    }
    out {alert: "sent", lamports: lamports}
  
  out {status: "ok", lamports: lamports}
```

**What this does:**
1. Checks Solana balance every hour (cron)
2. Compares to threshold (500M lamports)
3. Sends Slack alert if low
4. Returns status

**Token cost:**
- **First run:** ~200 tokens (compile + execute)
- **Subsequent runs:** ~5 tokens (just execute)
- **Savings vs Python:** 97%+ for hourly execution

## File Structure After Integration

```
ainl-cortex/
├── .claude-plugin/
│   └── plugin.json                    # Updated capabilities
├── mcp_server/
│   ├── server.py                      # Enhanced MCP server
│   ├── ainl_tools.py                  # NEW: AINL MCP tools
│   ├── ainl_context.py                # NEW: Context injection
│   └── ainl_patterns.py               # NEW: Pattern memory
├── hooks/
│   ├── ainl_detection.py              # NEW: Detect opportunities
│   └── ainl_validator.py              # NEW: Auto-validation
├── templates/ainl/                     # NEW: Template library
│   ├── api_endpoint.ainl
│   ├── monitor_workflow.ainl
│   ├── data_pipeline.ainl
│   ├── llm_workflow.ainl
│   └── blockchain_client.ainl
├── docs/
│   ├── AINL_LANGUAGE_GUIDE.md         # NEW: For Claude
│   ├── USER_GUIDE_AINL.md             # NEW: For users
│   └── IMPLEMENTATION_SUMMARY.md      # THIS FILE
├── CLAUDE.md                           # NEW: Plugin instructions
└── README.md                           # Updated with AINL
```

## Success Metrics

### Phase 1
- ✅ Claude validates .ainl syntax
- ✅ All MCP tools working
- ✅ Test coverage >80%

### Phase 2
- ✅ Claude suggests .ainl for 80%+ appropriate cases
- ✅ False positive rate <10%
- ✅ Context injection verified

### Phase 3
- ✅ Pattern memory has 10+ patterns
- ✅ Auto-validation catches 95%+ errors
- ✅ 10+ useful templates

### Phase 4
- ✅ Complete user guide
- ✅ Functional onboarding
- ✅ Token savings demonstrable
- ✅ Positive user feedback

## Getting Started (Post-Implementation)

### For Users

1. **Ask Claude to create a workflow:**
   ```
   "Create a monitor that checks my Solana balance hourly 
   and alerts me on Slack if it's below 1 SOL"
   ```

2. **Claude will:**
   - Suggest using AINL
   - Create a .ainl file
   - Validate syntax
   - Explain token savings
   - Help you run it

### For Developers

1. **Enable the plugin:**
   ```bash
   cd ~/.claude/plugins/ainl-cortex
   pip install -r requirements.txt
   ```

2. **Verify installation:** Restart Claude Code and check for the `[AINL Cortex]` banner and ~24 tools in `/mcp`.

3. **Use MCP tools in Claude:**
   - `ainl_validate` to check syntax
   - `ainl_compile` to see IR
   - `ainl_run` to execute

## Installation & Setup

### Quick Start

```bash
# 1. Navigate to plugin directory
cd ~/.claude/plugins/ainl-cortex

# 2. Install dependencies (includes ainativelang from PyPI)
pip install -r requirements.txt

# 3. Verify installation
python3 -c "import compiler_v2; from runtime.engine import RUNTIME_VERSION; print(f'AINL v{RUNTIME_VERSION}')"

# 4. Test MCP server
python3 mcp_server/server.py --help
```

### Dependencies

The plugin uses `ainativelang` from PyPI (v1.7.0+):

```txt
# requirements.txt
ainativelang[mcp]>=1.7.0  # Includes compiler, runtime, MCP tools
sqlite-utils>=3.30         # Graph memory storage
fastmcp>=0.2.0            # MCP server framework
pydantic>=2.0.0           # Data validation
```

All AINL imports work directly from the installed package:

```python
from compiler_v2 import AICodeCompiler
from runtime.engine import RuntimeEngine, RUNTIME_VERSION
from runtime.adapters.base import AdapterRegistry
from tooling.security_report import analyze_ir
```

## References

### Official Sources
- **PyPI Package:** https://pypi.org/project/ainativelang/
- **Website:** https://ainativelang.com
- **GitHub:** https://github.com/sbhooley/ainativelang

### Plugin Documentation
- **Full Plan:** `../AINL_INTEGRATION_PLAN.md`
- **User Guide:** `USER_GUIDE_AINL.md` (to be created)
- **Language Guide:** `AINL_LANGUAGE_GUIDE.md` (to be created)

### Local Reference (development)
- **AINL Repo:** `https://ainativelang.com`
- **AINL Spec:** `AI_Native_Lang/docs/AINL_SPEC.md`
- **Agent Guide:** `AI_Native_Lang/AGENTS.md`

---

**Status:** Planning Complete ✅  
**Integration Approach:** PyPI package-first  
**Next:** Begin Phase 1 Implementation  
**Timeline:** 4 weeks to full integration
