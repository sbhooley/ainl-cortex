# AINL First-Class Language Integration Plan for Claude Code

**Version:** 1.0  
**Date:** 2026-04-21  
**Status:** Planning Phase

## Executive Summary

This document outlines the strategy to make AI Native Lang (AINL) a first-class programming language within Claude Code through the ainl-cortex plugin. The goal is to enable Claude Code to fully understand AINL, utilize all AINL MCP tools, and proactively suggest using .ainl files for appropriate use cases.

## Background

### What is AINL?

AI Native Lang (AINL) is a **graph-canonical, agent-native programming language** designed specifically for AI agents to write deterministic, multi-step workflows:

- **Compact DSL**: Python-like syntax for human readability
- **Graph-native IR**: Compiles to deterministic intermediate representation
- **Token efficiency**: 90-95% token savings for recurring workflows (compile once, run many times)
- **Adapter-based**: Pluggable backends for databases, APIs, LLMs, blockchain, etc.
- **Two syntaxes**: Compact (recommended) and Opcode (low-level)

### Current State

**Existing:**
- ✅ `ainl-cortex` plugin provides graph-based memory for Claude Code sessions
- ✅ AINL runtime available on PyPI as `ainativelang` (v1.7.0+)
- ✅ MCP server implementation available in `ainativelang[mcp]` package
- ✅ ArmaraOS integration (desktop agent OS built on AINL)
- ✅ Local development repo at `/Users/clawdbot/.openclaw/workspace/AI_Native_Lang` (for reference)

**Missing:**
- ❌ Claude Code doesn't understand AINL syntax
- ❌ MCP tools not integrated into plugin
- ❌ No auto-suggestion for .ainl usage
- ❌ No syntax validation/compilation support in workflow
- ❌ No awareness of when AINL is applicable

**Integration Approach:**
- Use PyPI `ainativelang` package as primary dependency
- Local repo serves as reference documentation and development source
- Plugin imports directly from installed package

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                   Claude Code Session                    │
└──────────────────┬──────────────────────────────────────┘
                   │
    ┌──────────────┼──────────────┐
    │              │              │
┌───▼────┐   ┌─────▼─────┐   ┌───▼────┐
│Language│   │   AINL    │   │  Graph │
│Context │◄─►│    MCP    │◄─►│ Memory │
│ System │   │  Tools    │   │ System │
└────────┘   └─────┬─────┘   └────────┘
                   │
            ┌──────▼──────┐
            │    AINL     │
            │  Compiler   │
            │  + Runtime  │
            └─────────────┘
```

## Implementation Strategy

### Phase 1: Core Integration (Week 1)

#### 1.1 Language Awareness Documentation

**File:** `docs/AINL_LANGUAGE_GUIDE.md`

Create comprehensive documentation that Claude Code will use as context when working with AINL:

```markdown
# AINL Language Guide for Claude Code

## When to Suggest AINL

Suggest .ainl files when users ask for:
- Recurring workflows, monitors, scheduled jobs
- Multi-step automations with external APIs
- Data processing pipelines
- Blockchain interactions (Solana, etc.)
- AI agent workflows with tool calling
- Cost-sensitive operations (AINL saves 90-95% tokens on recurring tasks)

## AINL Syntax Quick Reference

### Compact Syntax (Recommended)
...
### Opcode Syntax
...
### Common Patterns
...
```

**Content includes:**
- Syntax reference (compact & opcode)
- When to use AINL vs Python/TS
- Common patterns library
- Adapter registry
- Error patterns and fixes
- Token savings use cases

#### 1.2 MCP Tools Integration

**File:** `mcp_server/ainl_tools.py`

Integrate AINL MCP tools using the `ainativelang` PyPI package:

```python
# Import from installed package
from compiler_v2 import AICodeCompiler
from compiler_diagnostics import CompilationDiagnosticError, CompilerContext
from runtime.engine import RuntimeEngine, AinlRuntimeError, RUNTIME_VERSION
from runtime.adapters.base import AdapterRegistry
from tooling.capability_grant import load_profile_as_grant, merge_grants
from tooling.security_report import analyze_ir
from tooling.mcp_ecosystem_import import (
    import_clawflow_mcp,
    import_agency_agent_mcp,
    list_ecosystem_templates,
)

# Core AINL MCP Tools
- ainl_validate       # Validate .ainl syntax (with --strict)
- ainl_compile        # Compile to IR JSON
- ainl_run            # Execute AINL workflows
- ainl_capabilities   # List available adapters/verbs
- ainl_security_report # Security analysis of IR

# Ecosystem Tools  
- ainl_import_clawflow     # Import from ClawFlow templates
- ainl_import_agency_agent # Import from Agency Agents
- ainl_list_ecosystem      # List available templates

# Advanced Tools
- ainl_ir_diff        # Compare IR graphs (blast radius)
- ainl_fitness_report # Pattern fitness scoring
- ainl_trace_export   # Export execution traces
```

**Integration approach:**
- Import directly from `ainativelang` package
- Wrap in MCP tool definitions using FastMCP
- Add to `.mcp.json` tool registry
- Handle sandboxing and permissions
- Use package resources for adapter manifests

#### 1.3 CLAUDE.md for Plugin

**File:** `CLAUDE.md`

Create plugin-level instructions for Claude Code:

```markdown
# AINL Plugin Instructions for Claude Code

You have access to the AINL (AI Native Lang) integration plugin.

## Your Responsibilities

1. **Recognize AINL opportunities**: When users describe workflows, 
   automations, monitors, or multi-step processes, suggest using .ainl
   
2. **Validate before compile**: Always run `ainl_validate --strict` 
   before compiling
   
3. **Use MCP tools**: Leverage ainl_capabilities to discover adapters
   
4. **Token awareness**: Explain AINL's token savings for recurring tasks

## Available AINL MCP Tools
...

## Common Use Cases
...

## Syntax Rules
...
```

### Phase 2: Smart Suggestions (Week 2)

#### 2.1 File Detection Hook

**File:** `hooks/ainl_detection.py`

Create a hook that fires on:
- `UserPromptSubmit` - Detect workflow/automation requests
- `PostToolUse` after `Read` - Detect .ainl files in workspace
- Project initialization - Suggest AINL for new projects

```python
def detect_ainl_opportunity(prompt: str, context: dict) -> dict:
    """
    Analyze user prompt and context to suggest AINL usage.
    
    Triggers:
    - Keywords: "workflow", "automation", "monitor", "schedule", "recurring"
    - Multi-step processes described
    - API integration requests
    - Cost concerns mentioned
    
    Returns:
    - suggestion: str (markdown message to inject)
    - confidence: float (0-1)
    - use_case: str (categorization)
    """
    ...
```

#### 2.2 Context Injection System

**File:** `mcp_server/ainl_context.py`

Inject AINL-specific context when:
- .ainl files detected in workspace
- User mentions workflows/automation
- Compiling or running AINL code

```python
class AINLContextManager:
    """Manages AINL language context injection."""
    
    def get_context(self, trigger: str) -> str:
        """
        Returns appropriate AINL documentation based on trigger.
        
        Triggers:
        - "syntax_error": Error patterns and fixes
        - "new_workflow": Getting started guide
        - "adapter_selection": Adapter catalog
        - "optimization": Token savings patterns
        """
        ...
```

### Phase 3: Advanced Features (Week 3)

#### 3.1 AINL Pattern Memory

**File:** `mcp_server/ainl_patterns.py`

Extend graph memory to recognize and store AINL workflow patterns:

```python
class AINLPatternStore:
    """
    Stores successful AINL patterns in graph memory.
    
    Pattern types:
    - API integration patterns
    - Data processing workflows
    - Monitoring scripts
    - Error handling patterns
    """
    
    def extract_pattern(self, ainl_source: str, success: bool) -> Pattern:
        """Extract reusable pattern from AINL code."""
        ...
        
    def recall_similar(self, query: str) -> List[Pattern]:
        """Find similar patterns from memory."""
        ...
```

#### 3.2 Auto-validation Integration

**File:** `hooks/ainl_validator.py`

Hook that auto-validates .ainl files on save:

```python
def on_file_save(event: dict) -> dict:
    """
    Auto-validate .ainl files after save.
    
    - Runs ainl_validate --strict
    - Shows diagnostics inline
    - Suggests fixes using agent_repair_steps
    """
    ...
```

#### 3.3 Template Library

**File:** `templates/ainl/`

Common AINL templates that Claude can reference:

```
templates/ainl/
├── api_endpoint.ainl          # REST API endpoint
├── monitor_workflow.ainl      # Monitoring script
├── data_pipeline.ainl         # ETL pipeline
├── llm_workflow.ainl          # AI agent workflow
├── blockchain_client.ainl     # Solana/Web3 client
└── README.md                  # Template usage guide
```

### Phase 4: User Experience (Week 4)

#### 4.1 User Documentation

**File:** `docs/USER_GUIDE_AINL.md`

User-facing guide:

```markdown
# Using AINL with Claude Code

## What is AINL?

AINL is a programming language designed for AI workflows...

## When Should I Use AINL?

- ✅ Recurring workflows and monitors
- ✅ Multi-step automations
- ✅ Cost-sensitive operations
- ✅ Blockchain interactions
- ❌ One-off scripts (use Python)
- ❌ Complex UIs (use React/TS)

## Getting Started
...

## Examples
...
```

#### 4.2 Interactive Onboarding

**File:** `cli/ainl_onboard.py`

CLI tool for first-time AINL users:

```bash
# Interactive setup
python3 cli/ainl_onboard.py

# Creates:
# - Example .ainl workflow
# - Validates and compiles it
# - Runs a demo
# - Explains token savings
```

## Technical Integration Details

### MCP Server Configuration

**Update:** `.mcp.json`

```json
{
  "name": "ainl-cortex",
  "version": "0.3.0",
  "description": "AINL-powered graph memory with first-class AINL language support",
  "mcp": {
    "server": "python3 mcp_server/server.py",
    "tools": [
      "graph_memory_*",
      "ainl_validate",
      "ainl_compile",
      "ainl_run",
      "ainl_capabilities",
      "ainl_security_report",
      "ainl_ir_diff",
      "ainl_import_*",
      "ainl_list_ecosystem"
    ],
    "resources": [
      "ainl://adapter-manifest",
      "ainl://authoring-cheatsheet",
      "ainl://security-profiles",
      "ainl://impact-checklist",
      "ainl://run-readiness"
    ]
  }
}
```

**Package-based resource loading:**

```python
# Resources come from installed package
from importlib.resources import files
import ainativelang

def load_adapter_manifest():
    """Load adapter manifest from package resources."""
    tooling = files('ainativelang').joinpath('tooling')
    manifest_path = tooling / 'adapter_manifest.json'
    return json.loads(manifest_path.read_text())
```

### Dependency Management

**Update:** `requirements.txt`

```txt
# Existing dependencies
sqlite-utils>=3.30
fastmcp>=0.2.0
pydantic>=2.0.0

# AINL core package with MCP extras
ainativelang[mcp]>=1.7.0

# Additional dependencies (pulled in by ainativelang)
# - pyyaml>=6.0 (config files)
# - httpx>=0.24.0 (HTTP adapter)
# - mcp>=1.0.0 (MCP server)
```

**Installation:**

```bash
cd ~/.claude/plugins/ainl-cortex
pip install -r requirements.txt
```

**Package structure:**
- `ainativelang` provides: compiler, runtime, adapters, tooling
- `ainativelang[mcp]` adds: FastMCP, MCP server dependencies
- All imports work directly from the installed package
- No local repo path configuration needed

### Environment Variables

```bash
# AINL runtime configuration
AINL_CONFIG=/path/to/config.yaml          # LLM/adapter config (optional)
AINL_MCP_EXPOSURE_PROFILE=full            # Expose all MCP tools
AINL_STRICT_MODE=1                        # Enable strict validation by default
AINL_HOST_ADAPTER_ALLOWLIST=http,fs,cache # Allowed adapters

# Plugin-specific
AINL_PLUGIN_TEMPLATES_DIR=~/.claude/plugins/ainl-cortex/templates/ainl
AINL_PATTERN_MEMORY_ENABLED=1             # Store AINL patterns in graph memory

# Package discovery (auto-detected from pip installation)
# No PYTHONPATH configuration needed - imports work directly
```

**Config file example** (`~/.ainl/config.yaml`):

```yaml
# Optional: LLM adapter configuration
llm:
  default: openrouter
  providers:
    openrouter:
      api_key: ${OPENROUTER_API_KEY}
      base_url: https://openrouter.ai/api/v1
    
# Optional: HTTP adapter defaults  
http:
  timeout_s: 30
  allow_hosts: []  # Empty = allow all (use with caution)
  
# Optional: File system adapter
fs:
  sandbox_root: /tmp/ainl-sandbox
```

## File Structure Changes

```
ainl-cortex/
├── .claude-plugin/
│   └── plugin.json                    # Updated with AINL capabilities
├── mcp_server/
│   ├── server.py                      # Main MCP server (enhanced)
│   ├── ainl_tools.py                  # NEW: AINL MCP tool wrappers
│   ├── ainl_context.py                # NEW: Context injection logic
│   └── ainl_patterns.py               # NEW: Pattern memory for AINL
├── hooks/
│   ├── ainl_detection.py              # NEW: Detect AINL opportunities
│   └── ainl_validator.py              # NEW: Auto-validate .ainl files
├── cli/
│   ├── ainl_cli.py                    # NEW: AINL CLI utilities
│   └── ainl_onboard.py                # NEW: Interactive onboarding
├── templates/
│   └── ainl/                          # NEW: AINL template library
│       ├── api_endpoint.ainl
│       ├── monitor_workflow.ainl
│       ├── data_pipeline.ainl
│       └── README.md
├── docs/
│   ├── AINL_LANGUAGE_GUIDE.md         # NEW: Language reference for Claude
│   ├── USER_GUIDE_AINL.md             # NEW: User-facing guide
│   └── AINL_INTEGRATION_PLAN.md       # THIS FILE
├── tests/
│   ├── test_ainl_tools.py             # NEW: Test MCP tools
│   ├── test_ainl_detection.py         # NEW: Test detection logic
│   └── test_ainl_patterns.py          # NEW: Test pattern memory
├── CLAUDE.md                           # NEW: Plugin instructions for Claude
├── requirements.txt                    # Updated with AINL deps
└── README.md                           # Updated with AINL features
```

## Token Savings Analysis

### Why AINL Matters for Cost

Traditional approach (prompt-based):
```
User: "Check Solana balance and alert if low"
→ Agent generates Python script (500 tokens)
→ Runs every hour: 500 tokens × 24 = 12,000 tokens/day
→ Cost: ~$0.12/day (at $10/1M tokens)
```

AINL approach:
```
User: "Check Solana balance and alert if low"
→ Agent generates .ainl workflow (200 tokens, once)
→ Compiles to IR (50 tokens)
→ Runs every hour: ~5 tokens × 24 = 120 tokens/day
→ Cost: ~$0.001/day (at $10/1M tokens)
```

**Savings: 99% reduction for recurring workflows**

## Use Case Matrix

| Use Case | Python/TS | AINL | Recommendation |
|----------|-----------|------|----------------|
| One-off data analysis | ✅ | ❌ | Python |
| Recurring monitor | ❌ | ✅ | AINL (90-95% savings) |
| Complex web UI | ✅ | ❌ | React/TS |
| API endpoint | ⚠️ | ✅ | AINL (then emit to FastAPI) |
| Blockchain client | ❌ | ✅ | AINL (specialized adapters) |
| Multi-step automation | ⚠️ | ✅ | AINL (deterministic graphs) |
| ML training script | ✅ | ❌ | Python |
| Scheduled job | ❌ | ✅ | AINL (built-in cron) |
| Real-time dashboard | ✅ | ❌ | React/TS |
| AI agent workflow | ⚠️ | ✅ | AINL (graph-native) |

## Success Metrics

### Phase 1 (Core Integration)
- [ ] Claude Code can validate .ainl syntax
- [ ] All MCP tools integrated and functional
- [ ] Language guide accessible to Claude
- [ ] Test coverage >80%

### Phase 2 (Smart Suggestions)
- [ ] Claude suggests .ainl for 80%+ of appropriate use cases
- [ ] False positive rate <10%
- [ ] .ainl file detection working
- [ ] Context injection verified

### Phase 3 (Advanced Features)
- [ ] Pattern memory stores 10+ successful AINL patterns
- [ ] Auto-validation catches 95%+ syntax errors
- [ ] Template library has 10+ useful templates
- [ ] Pattern recall accuracy >70%

### Phase 4 (User Experience)
- [ ] User guide complete and clear
- [ ] Onboarding tutorial functional
- [ ] Token savings demonstrable in examples
- [ ] Positive user feedback

## Risk Mitigation

### Technical Risks

1. **Package Version Compatibility**
   - Risk: PyPI package updates may break plugin
   - Mitigation: Pin to `ainativelang>=1.7.0,<2.0.0`, test before upgrading
   
2. **MCP Tool Performance**
   - Risk: Compilation/validation may be slow
   - Mitigation: Cache compiled IR, async tool execution, process pooling
   
3. **Context Size**
   - Risk: AINL docs may be too large for context
   - Mitigation: Lazy loading, on-demand documentation fetch, summarized guides
   
4. **Adapter Security**
   - Risk: Unrestricted adapter access could be dangerous
   - Mitigation: Use security profiles, adapter allowlists, sandboxing

### User Experience Risks

1. **Learning Curve**
   - Risk: AINL syntax may confuse users
   - Mitigation: Excellent documentation, templates, auto-suggestions, interactive tutorials
   
2. **Over-suggestion**
   - Risk: Claude suggests AINL too often
   - Mitigation: Clear triggers, confidence thresholds >0.7, user feedback loop
   
3. **Package Installation**
   - Risk: Users may have trouble installing dependencies
   - Mitigation: Clear error messages, fallback to documentation-only mode, auto-install script

## Timeline

| Week | Phase | Deliverables |
|------|-------|--------------|
| 1 | Core Integration | Language guide, MCP tools, CLAUDE.md |
| 2 | Smart Suggestions | Detection hooks, context injection |
| 3 | Advanced Features | Pattern memory, auto-validation, templates |
| 4 | User Experience | User guide, onboarding, polish |

## Next Steps

1. ✅ Create this plan document
2. [ ] Review with stakeholders
3. [ ] Set up development environment
4. [ ] Begin Phase 1 implementation
5. [ ] Create test suite
6. [ ] Iterate based on feedback

## References

### PyPI Package
- **PyPI:** https://pypi.org/project/ainativelang/
- **Package Version:** 1.7.0+
- **Installation:** `pip install ainativelang[mcp]`

### Documentation
- **AINL Spec:** https://github.com/sbhooley/ainativelang (official repo)
- **Local Reference:** `/Users/clawdbot/.openclaw/workspace/AI_Native_Lang`
- **Website:** https://ainativelang.com

### Source Code (for development reference)
- AINL Repository: `/Users/clawdbot/.openclaw/workspace/AI_Native_Lang`
- AINL Spec: `docs/AINL_SPEC.md`
- MCP Server Reference: `scripts/ainl_mcp_server.py`
- Agent Guide: `AGENTS.md`
- ArmaraOS Integration: `docs/ARMARAOS_INTEGRATION.md`

### Package Imports
```python
# All imports from installed package
from compiler_v2 import AICodeCompiler
from runtime.engine import RuntimeEngine, RUNTIME_VERSION
from runtime.adapters.base import AdapterRegistry
from tooling.security_report import analyze_ir
from tooling.mcp_ecosystem_import import import_clawflow_mcp
```

---

**Author:** Claude Code Plugin Team  
**Last Updated:** 2026-04-21  
**Integration Approach:** PyPI package-first
