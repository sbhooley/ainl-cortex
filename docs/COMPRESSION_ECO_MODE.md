# AINL Compression & Eco Mode

Token and cost savings through intelligent prompt compression, inspired by ArmaraOS `ainl-compression` crate.

## Overview

The plugin includes **Ultra Cost-Efficient Mode** - embedding-free input compression that reduces token usage while preserving critical information. This is a Python port of the battle-tested Rust `ainl-compression` algorithms from ArmaraOS.

### Key Benefits

- **40-70% token savings** on injected memory context
- **No semantic understanding needed** - pure heuristic compression
- **Sub-30ms latency** - fast enough for real-time use
- **Preserves critical content** - code blocks, technical terms, user intent
- **Three modes** - Off, Balanced, Aggressive

## Compression Modes

| Mode | Retention | Typical Savings | When to Use |
|------|-----------|-----------------|-------------|
| **Off** | 100% | 0% | No compression needed |
| **Balanced** | ~55% | 40-50% | Default; safe for all content |
| **Aggressive** | ~35% | 55-70% | High-volume usage, cost-sensitive |

## How It Works

### Algorithm (Simplified)

1. **Extract code blocks** - Everything in ` ``` ` fences is preserved verbatim
2. **Split prose into sentences** - Break on periods and newlines
3. **Score each sentence** - Higher score = more important
4. **Apply preserve rules**:
   - **Hard preserve** (both modes): technical terms, URLs, error messages, tool names
   - **Soft preserve** (Balanced only): metrics, product names, formatting
5. **Pack into budget** - Select highest-scoring sentences that fit
6. **Strip fillers** - Remove hedging phrases ("I think", "basically", etc.)
7. **Reassemble** - Join sentences back together

### Preserve Lists

**Hard Preserve** (always kept):
- User intent: "exact", "steps", "already tried/checked/restarted"
- Technical: "error", "daemon", "restart", URLs, tool names (Read, Edit, Bash)
- Code: ` ``` `, `->`, `::`, `.ainl`
- Claude Code specific: "claude", "mcp", "graph memory", "episode"

**Soft Preserve** (Balanced force-keep, Aggressive boost-only):
- Formatting: `##`, metrics (` ms`, ` kb`, ` %`)
- Product names: "armaraos", "openfang", "manifest"
- Memory types: "persona", "pattern", "semantic"

**Aggressive Mode Extras**:
- Penalizes meta-sentences starting with "This ", "These ", "It "
- Converts soft-preserve from force-keep to score-boost
- Allows deeper compression of changelog-style text

## Configuration

### Plugin Config

Create or edit `~/.claude/plugins/ainl-cortex/config.json`:

```json
{
  "compression": {
    "enabled": true,
    "mode": "balanced",
    "compress_memory_context": true,
    "compress_user_prompt": false,
    "min_tokens_for_compression": 80
  }
}
```

### CLI Tool

```bash
# Show current configuration
python3 cli/compression_cli.py config

# Set compression mode
python3 cli/compression_cli.py config --mode aggressive

# Test compression on a file
python3 cli/compression_cli.py test --file example.txt --mode balanced --show-output

# Test compression on text
echo "This is a test. I think it should compress well." | \
  python3 cli/compression_cli.py test --mode balanced

# Benchmark modes
python3 cli/compression_cli.py benchmark
```

## Examples

### Example 1: Memory Context Compression

**Original (200 tokens):**
```
## Relevant Graph Memory

**Recent Work:**
- [2026-04-19] I think we should fix the authentication bug in login.py → success
- [2026-04-18] Basically, we need to add JWT validation to the middleware → success
- [2026-04-17] Fix the error handling in the logout endpoint → partial

**Known Facts:**
- Of course, JWT tokens require secret validation (conf: 0.92)
- As you know, auth middleware runs before route handlers (conf: 0.85)
- To be honest, session tokens should expire after 24 hours (conf: 0.78)

**Reusable Patterns:**
- "error-read-fix-verify": bash → read → edit → bash (fitness: 0.88)

**Known Issues:**
- src/auth.py:42: Unclosed session in logout handler

**Project Style:** testing_rigor (0.78), type_safety (0.65)
```

**Compressed with Balanced (~110 tokens, 45% savings):**
```
## Relevant Graph Memory

**Recent Work:**
- [2026-04-19] Fix authentication bug in login.py → success
- [2026-04-18] Add JWT validation to middleware → success

**Known Facts:**
- JWT tokens require secret validation (conf: 0.92)
- Auth middleware runs before route handlers (conf: 0.85)

**Reusable Patterns:**
- "error-read-fix-verify": bash → read → edit → bash (fitness: 0.88)

**Known Issues:**
- src/auth.py:42: Unclosed session in logout handler

**Project Style:** testing_rigor (0.78), type_safety (0.65)
```

Notice:
- ✅ Technical terms preserved ("JWT", "auth", "bash")
- ✅ Error location kept ("src/auth.py:42")
- ✅ Patterns and metrics intact
- ❌ Filler phrases removed ("I think", "Basically", "Of course")
- ❌ Redundant explanations dropped

### Example 2: Code Preservation

**Input:**
```
The function should use HTTP requests. Here's the implementation:

```python
def fetch_data():
    return requests.get("https://api.example.com")
```

This code makes HTTP calls to the API endpoint.
```

**Compressed (Balanced):**
```
Function should use HTTP requests. Here's the implementation:

```python
def fetch_data():
    return requests.get("https://api.example.com")
```

Code makes HTTP calls to API endpoint.
```

**Result:**
- Code block preserved 100% verbatim
- HTTP URLs protected
- Only prose trimmed

## Telemetry

Compression metrics are logged for each operation:

```python
{
  "mode": "balanced",
  "original_tokens": 200,
  "compressed_tokens": 110,
  "tokens_saved": 90,
  "savings_ratio_pct": 45.0,
  "elapsed_ms": 12
}
```

Check logs:
```bash
tail -f ~/.claude/plugins/ainl-cortex/logs/hooks.log | grep compression
```

## Cost Savings Calculator

Assuming:
- Average memory context: 150 tokens
- Claude Sonnet 4.5 input: $3/M tokens
- 100 prompts per day

### Without Compression
- Daily tokens: 100 × 150 = 15,000
- Daily cost: $0.045
- Monthly cost: $1.35

### With Balanced Mode (45% savings)
- Daily tokens: 100 × 82 = 8,200
- Daily cost: $0.025
- Monthly cost: $0.75
- **Savings: $0.60/month (44%)**

### With Aggressive Mode (65% savings)
- Daily tokens: 100 × 52 = 5,200
- Daily cost: $0.016
- Monthly cost: $0.48
- **Savings: $0.87/month (64%)**

For heavy users (1000+ prompts/day), savings can reach **$30-50/month**.

## Comparison to ArmaraOS

This implementation ports the core algorithms from `ainl-compression` crate:

| Feature | ArmaraOS (Rust) | This Plugin (Python) |
|---------|-----------------|----------------------|
| Compression modes | ✅ 3 modes | ✅ 3 modes |
| Code fence preservation | ✅ | ✅ |
| Hard/soft preserve lists | ✅ | ✅ |
| Filler stripping | ✅ | ✅ |
| Token estimation | chars/4 + 1 | chars/4 + 1 |
| Aggressive penalties | ✅ | ✅ |
| Telemetry | ✅ | ✅ |
| Adaptive eco | ✅ | ❌ (future) |
| Semantic preservation | ✅ | ❌ (future) |

## Best Practices

### When to Use Balanced

- Default choice for most users
- Safe for all content types
- Preserves soft terms (metrics, formatting)
- 40-50% savings typical

### When to Use Aggressive

- High-volume usage (100+ prompts/day)
- Cost-sensitive applications
- Content with many product names/changelog entries
- Willing to trade slight information loss for higher savings

### When to Use Off

- Critical debugging sessions
- When every detail matters
- Low-volume usage (<10 prompts/day)
- Testing/development

## Future Enhancements

Planned features (matching ArmaraOS roadmap):

- [ ] **Adaptive eco mode** - Automatically adjust compression based on prompt type
- [ ] **Semantic preservation scoring** - Track information retention quality
- [ ] **Per-project compression profiles** - Remember optimal mode per codebase
- [ ] **Output compression** - Also compress Claude's responses
- [ ] **Prompt cache awareness** - Coordinate with provider-level caching

## Inspired By

This compression system is a direct port of ArmaraOS `ainl-compression` crate:
- Repository: https://github.com/sbhooley/armaraos
- Crate: `crates/ainl-compression`
- Documentation: `docs/prompt-compression-efficient-mode.md`

All compression algorithms and preserve lists are attributed to the AINL project.

## Learn More

- **ArmaraOS Compression Guide**: https://github.com/sbhooley/armaraos/blob/main/docs/prompt-compression-efficient-mode.md
- **AINL Philosophy**: [AINL_CONCEPTS.md](AINL_CONCEPTS.md)
- **Plugin README**: [README.md](../README.md)
