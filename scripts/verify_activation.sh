#!/bin/bash
# Verify AINL Graph Memory plugin activation
# Run this to check if the plugin is properly configured

echo "=== AINL Graph Memory Plugin Activation Check ==="
echo ""

# Check plugin directory
if [ -d ~/.claude/plugins/ainl-graph-memory ]; then
    echo "✅ Plugin directory exists"
else
    echo "❌ Plugin directory not found"
    exit 1
fi

# Check plugin.json
if [ -f ~/.claude/plugins/ainl-graph-memory/.claude-plugin/plugin.json ]; then
    echo "✅ Plugin metadata (plugin.json) exists"
else
    echo "❌ Plugin metadata not found"
    exit 1
fi

# Check hooks.json
if [ -f ~/.claude/plugins/ainl-graph-memory/hooks/hooks.json ]; then
    echo "✅ Hooks configuration (hooks.json) exists"
else
    echo "❌ Hooks configuration not found"
    exit 1
fi

# Check MCP server config
if [ -f ~/.claude/plugins/ainl-graph-memory/.mcp.json ]; then
    echo "✅ MCP server configuration exists"
else
    echo "❌ MCP server configuration not found"
    exit 1
fi

# Check hooks are executable
hook_count=0
for hook in ~/.claude/plugins/ainl-graph-memory/hooks/*.py; do
    if [ -x "$hook" ]; then
        ((hook_count++))
    fi
done
echo "✅ Found $hook_count executable hooks"

# Test Python dependencies
echo ""
echo "Checking Python dependencies..."
cd ~/.claude/plugins/ainl-graph-memory
if python3 -c "import sys; sys.path.insert(0, '.'); from mcp_server.config import get_config; get_config()" 2>/dev/null; then
    echo "✅ Python dependencies OK"
else
    echo "⚠️  Some Python dependencies may be missing"
    echo "   Run: pip install -r requirements.txt"
fi

# Test configuration loading
echo ""
echo "Testing configuration..."
python3 -c "
import sys
sys.path.insert(0, '.')
from mcp_server.config import get_config
from mcp_server.compression import EfficientMode

config = get_config()
print('✅ Config loaded successfully')
print(f'   Compression enabled: {config.is_compression_enabled()}')
print(f'   Compression mode: {config.get_compression_mode().value}')
print(f'   Memory compression: {config.is_compression_memory_enabled()}')
print(f'   Adaptive eco: {config.is_adaptive_eco_enabled()}')
print(f'   Semantic scoring: {config.is_semantic_scoring_enabled()}')
print(f'   Project profiles: {config.is_project_profiles_enabled()}')
print(f'   Cache awareness: {config.is_cache_awareness_enabled()}')
" 2>/dev/null || echo "⚠️  Configuration test failed"

echo ""
echo "=== Plugin Activation Status ==="
echo ""
echo "The plugin is INSTALLED and configured."
echo ""
echo "Claude Code will automatically load plugins from ~/.claude/plugins/"
echo "on startup. The hooks will fire on the following events:"
echo "  - UserPromptSubmit: Inject memory context before each response"
echo "  - PostToolUse: Capture tool usage in graph"
echo "  - PreCompact/PostCompact: Handle conversation compaction"
echo "  - Stop: Flush memory on session end"
echo ""
echo "To verify the plugin is active in a Claude Code session:"
echo "1. Start/restart Claude Code"
echo "2. Run any command that triggers a hook"
echo "3. Check for memory context injection in responses"
echo "4. Or check: ~/.claude/projects/[project-hash]/graph_memory/ainl_memory.db"
echo ""
echo "✅ Plugin activation complete!"
