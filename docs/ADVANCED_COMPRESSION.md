# Advanced Compression Features

**AINL Cortex v0.2** - Production-grade compression enhancements

## Overview

The advanced compression system adds five intelligent enhancements to the base AINL compression:

1. **Adaptive Eco Mode** - Content-aware compression level selection
2. **Semantic Preservation Scoring** - Quality tracking without embeddings
3. **Per-Project Profiles** - Learn optimal mode for each codebase
4. **Prompt Cache Awareness** - Coordinate with provider-level caching
5. **Output Compression** - Optional compression of Claude's responses

All enhancements work together in a **unified compression pipeline**.

## Quick Start

### Installation

Already included! If you have AINL Cortex installed, you have these features.

### Basic Usage

The pipeline runs automatically when memory context is injected. No configuration needed.

### Advanced CLI

```bash
# Test the pipeline
echo "Your text here" | python3 cli/compression_advanced_cli.py test -p myproject

# Show configuration
python3 cli/compression_advanced_cli.py config

# Show statistics
python3 cli/compression_advanced_cli.py adaptive    # Adaptive mode stats
python3 cli/compression_advanced_cli.py quality     # Quality scores
python3 cli/compression_advanced_cli.py profile     # Project profiles

# Set preferred mode for a project
python3 cli/compression_advanced_cli.py set-mode -p myproject -m aggressive

# Auto-detect best mode
python3 cli/compression_advanced_cli.py auto-detect -p myproject --apply
```

## Feature Details

### 1. Adaptive Eco Mode

**Automatically selects the best compression mode based on content type.**

#### How It Works

Content analyzer detects:
- Code ratio (code blocks in text)
- Technical density (technical terms per word)
- Question vs command intent
- URLs and file paths

Mode recommender applies rules:
- High code (>40%) → OFF (preserve exactly)
- Technical + short → BALANCED
- Long narrative → AGGRESSIVE
- Has URLs/paths → BALANCED (safe)

#### Configuration

```json
{
  "compression": {
    "adaptive_eco": {
      "enabled": true,
      "min_confidence": 0.7,
      "hysteresis_count": 2
    }
  }
}
```

- `min_confidence`: Minimum confidence (0-1) to override manual mode
- `hysteresis_count`: Consistent recommendations before switching

#### Example

```python
# High code content → OFF mode
text = """
```python
def authenticate(token):
    verify_signature(token)
    check_expiration(token)
```
"""
# Recommendation: OFF (confidence 0.9)

# Long narrative → AGGRESSIVE mode  
text = "This is a detailed description..." * 50
# Recommendation: AGGRESSIVE (confidence 0.75)
```

### 2. Semantic Preservation Scoring

**Tracks compression quality without expensive embeddings.**

#### Metrics

- **Overall Score** (0-1): Weighted quality score
- **Key Term Retention**: Critical terms preserved (errors, URLs, code)
- **Structural Similarity**: Sentence/paragraph preservation
- **Code Preservation**: Code blocks preserved exactly
- **URL Preservation**: Links preserved

#### How It Works

Embedding-free heuristics:
- Extract key terms (technical words, CamelCase, snake_case)
- Count sentences, paragraphs, lines
- Check code fence preservation
- Verify URL preservation

Quality thresholds:
- Min overall: 70%
- Min key terms: 80%
- Code must be perfect (100%)

**Automatic fallback**: If quality too low, pipeline uses original text.

#### Configuration

```json
{
  "compression": {
    "semantic_scoring": {
      "enabled": true,
      "min_overall_score": 0.70,
      "min_key_term_retention": 0.80,
      "track_quality": true
    }
  }
}
```

### 3. Per-Project Compression Profiles

**Remember the best compression mode for each codebase.**

#### How It Works

For each project:
- Track compression stats by mode
- Calculate effectiveness (savings + quality)
- Auto-detect best mode after 5+ compressions
- Store preferences in `~/.claude/plugins/ainl-graph-memory/profiles/`

#### Auto-Detection

Algorithm balances savings and quality:
```
score = 0.6 * avg_savings_ratio + 0.4 * avg_quality_score
```

Best scoring mode becomes preferred (if sufficient data).

#### Configuration

```json
{
  "compression": {
    "project_profiles": {
      "enabled": true,
      "auto_detect_mode": true,
      "min_compressions_for_detection": 5
    }
  }
}
```

#### CLI Usage

```bash
# Show profile for project
python3 cli/compression_advanced_cli.py profile -p myproject

# Manually set preferred mode
python3 cli/compression_advanced_cli.py set-mode -p myproject -m balanced

# Auto-detect and apply
python3 cli/compression_advanced_cli.py auto-detect -p myproject --apply

# List all project profiles
python3 cli/compression_advanced_cli.py profile
```

### 4. Prompt Cache Awareness

**Coordinates compression with provider-level prompt caching.**

#### The Problem

Anthropic/OpenAI cache prompts for 5 minutes. Changing compression mode breaks the cache, negating token savings.

#### The Solution

Cache coordinator:
1. Tracks current mode per project
2. Checks if cache is warm (< 5min since mode set)
3. Uses **hysteresis** to prevent oscillation
4. Only switches mode after 2min of consistent recommendation

#### How It Works

```
Warm cache (< 5min):
  → Keep current mode (preserve cache)

Cold cache (> 5min):
  → Switch to recommended mode

Hysteresis (prevent oscillation):
  → Require 2min of consistent recommendation before switch
```

#### Configuration

```json
{
  "compression": {
    "cache_awareness": {
      "enabled": true,
      "cache_ttl": 300,
      "hysteresis_duration": 120,
      "preserve_warm_cache": true
    }
  }
}
```

- `cache_ttl`: Cache TTL in seconds (300 = 5min, Anthropic default)
- `hysteresis_duration`: Seconds before allowing mode change

#### CLI Usage

```bash
# Show cache state for project
python3 cli/compression_advanced_cli.py cache -p myproject
```

### 5. Output Compression (Optional)

**Compress Claude's responses to save output tokens.**

⚠️ **Disabled by default** - This changes Claude's responses. Enable carefully.

#### How It Works

More conservative than input compression:
- Preserves all code blocks exactly
- Preserves file paths and line numbers
- Preserves numbered lists and steps
- Only compresses responses > 200 tokens
- Optional compression badge

#### Configuration

```json
{
  "compression": {
    "output": {
      "enabled": false,
      "mode": "balanced",
      "min_length_tokens": 200,
      "show_badge": false
    }
  }
}
```

**Not recommended** unless you have very long narrative responses.

## Pipeline Flow

The unified pipeline coordinates all features:

```
1. Get base mode from config
   ↓
2. Check project profile → preferred mode?
   ↓
3. Run adaptive eco → content-based override?
   ↓
4. Check cache awareness → should preserve cache?
   ↓
5. Compress with final mode
   ↓
6. Score semantic preservation
   ↓
7. Fallback to original if quality too low
   ↓
8. Record outcome for learning
```

## Configuration File

Full configuration in `~/.claude/plugins/ainl-graph-memory/.mcp.json`:

```json
{
  "compression": {
    "mode": "balanced",
    "compress_memory_context": true,
    
    "adaptive_eco": {
      "enabled": true,
      "min_confidence": 0.7,
      "hysteresis_count": 2
    },
    
    "semantic_scoring": {
      "enabled": true,
      "min_overall_score": 0.70,
      "min_key_term_retention": 0.80,
      "track_quality": true
    },
    
    "project_profiles": {
      "enabled": true,
      "auto_detect_mode": true,
      "min_compressions_for_detection": 5
    },
    
    "cache_awareness": {
      "enabled": true,
      "cache_ttl": 300,
      "hysteresis_duration": 120,
      "preserve_warm_cache": true
    },
    
    "output": {
      "enabled": false,
      "mode": "balanced",
      "min_length_tokens": 200,
      "show_badge": false
    }
  },
  
  "telemetry": {
    "track_compression_savings": true,
    "track_quality_scores": true,
    "track_adaptive_decisions": true
  }
}
```

## Performance

### Token Savings

- **Balanced mode**: 40-50% reduction
- **Aggressive mode**: 55-70% reduction
- **Cache preservation**: 100% on cached prefix (if warm)

### Latency

All compression operations: **< 30ms**

No LLM calls, no embeddings, pure algorithmic compression.

### Quality

Semantic scoring across 100+ test compressions:
- Average overall: 82%
- Average key term retention: 91%
- Code preservation: 100%

## Testing

Run integration tests:

```bash
# Quick smoke test
echo "test message" | python3 cli/compression_advanced_cli.py test -p test

# Full integration suite
./tests/integration_test.sh

# Unit tests (requires pytest)
pytest tests/test_compression_pipeline.py -v
```

## Telemetry

Track compression effectiveness:

```bash
# Adaptive mode effectiveness
python3 cli/compression_advanced_cli.py adaptive

# Quality distribution
python3 cli/compression_advanced_cli.py quality

# Per-project stats
python3 cli/compression_advanced_cli.py profile -p myproject
```

## Troubleshooting

### Compression not working

1. Check config: `python3 cli/compression_advanced_cli.py config`
2. Test pipeline: `echo "test" | python3 cli/compression_advanced_cli.py test -p test`
3. Check logs in `~/.claude/plugins/ainl-graph-memory/logs/`

### Quality warnings

If you see low quality scores:
- Text is too short (< 80 tokens)
- Text is mostly code (adaptive should switch to OFF)
- Aggressive mode on technical content (try balanced)

### Cache not preserved

Cache awareness only works when:
- Enabled in config
- Same project used consistently
- Within cache TTL window (5min)

## Advanced: Custom Rules

Want custom adaptive rules? Edit `mcp_server/adaptive_eco.py`:

```python
class ModeRecommender:
    def recommend(self, text: str, current_mode: EfficientMode):
        # Add your custom rule
        if "production deploy" in text.lower():
            return ModeRecommendation(
                mode=EfficientMode.OFF,
                confidence=0.95,
                reason="Production deploy, preserve all details"
            )
        # ... existing rules
```

## Learn More

- [AINL Concepts](AINL_CONCEPTS.md) - Core architecture
- [Compression Eco Mode](COMPRESSION_ECO_MODE.md) - Base compression
- [ArmaraOS AINL](https://github.com/sbhooley/armaraos) - Original implementation

---

**Built with the AINL unified graph execution engine architecture**
