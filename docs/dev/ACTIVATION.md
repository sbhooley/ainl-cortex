# AINL Graph Memory Plugin - Activation Guide

## Current Status

✅ **Plugin is INSTALLED and ACTIVE**

The plugin is located at: `~/.claude/plugins/ainl-graph-memory/`

Claude Code automatically loads plugins from this directory on startup.

## Persistence Across Restarts

The plugin **automatically persists** across terminal/Claude Code restarts because:

1. **Plugin Directory**: Located in `~/.claude/plugins/` (permanent location)
2. **Proper Structure**: Contains required files:
   - `.claude-plugin/plugin.json` - Plugin metadata
   - `hooks/hooks.json` - Hook definitions
   - `.mcp.json` - MCP server configuration
3. **Executable Hooks**: All 5 hooks are marked executable
4. **Configuration**: Settings stored in `.mcp.json` (persistent)

## How Activation Works

### Automatic Discovery

Claude Code scans `~/.claude/plugins/` on startup and loads any plugin with:
- Valid `.claude-plugin/plugin.json`
- Properly defined hooks in `hooks/hooks.json`
- Executable hook scripts

### Hooks Registered

The plugin registers these lifecycle hooks:

| Hook | When It Fires | What It Does |
|------|---------------|--------------|
| **UserPromptSubmit** | Before Claude responds | Inject relevant memory context |
| **PostToolUse** | After tool execution | Capture tool usage in graph |
| **PreCompact** | Before conversation compression | Prepare for compaction |
| **PostCompact** | After conversation compression | Update memory after compaction |
| **Stop** | When session ends | Flush memory to disk |

### MCP Server (Optional)

The plugin also provides an MCP server for advanced memory operations:
- Server: `python3 mcp_server/server.py`
- Tools: Graph search, memory queries, pattern analysis
- Auto-configured via `.mcp.json`

## Verification

### Quick Check

Run the verification script:

```bash
cd ~/.claude/plugins/ainl-graph-memory
./verify_activation.sh
```

You should see all ✅ checkmarks.

### Verify It's Working in Claude Code

#### Method 1: Check Memory Database

After using Claude Code for a few interactions:

```bash
# List project memory databases
find ~/.claude/projects -name "ainl_memory.db"

# If you see databases, the plugin is working!
```

#### Method 2: Check Memory Content

```bash
# View recent episodes
python3 cli/memory_cli.py list --type episode --limit 5

# Search memory
python3 cli/memory_cli.py search "your recent work"
```

#### Method 3: Look for Memory Context

When Claude responds, look for injected memory context (usually at the start of responses or in Claude's thinking).

### Check Compression is Active

```bash
# View compression settings
python3 cli/compression_cli.py config

# Test compression
echo "Long text here" | python3 cli/compression_advanced_cli.py test -p test
```

## Troubleshooting

### Plugin Not Loading

If the plugin doesn't seem active:

1. **Restart Claude Code**
   ```bash
   # Exit Claude Code completely and restart
   ```

2. **Check Plugin Structure**
   ```bash
   cd ~/.claude/plugins/ainl-graph-memory
   ./verify_activation.sh
   ```

3. **Check Permissions**
   ```bash
   # Ensure hooks are executable
   chmod +x hooks/*.py
   ```

4. **Check Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

### Hooks Not Firing

If memory isn't being captured:

1. **Check Hook Logs**
   ```bash
   # Check Claude Code logs for hook errors
   tail -f ~/.claude/sessions/*/logs/*.log
   ```

2. **Test Hook Manually**
   ```bash
   # Test if hook script works
   echo '{"projectId":"test","workingDir":"'$PWD'","prompt":"test"}' | \
     python3 hooks/user_prompt_submit.py
   ```

3. **Check Database**
   ```bash
   # List memory databases
   find ~/.claude/projects -name "ainl_memory.db" -ls
   ```

### Compression Not Working

If compression isn't applying:

1. **Check Config**
   ```bash
   python3 -c "
   import sys; sys.path.insert(0, '.')
   from mcp_server.config import get_config
   c = get_config()
   print('Enabled:', c.is_compression_enabled())
   print('Mode:', c.get_compression_mode())
   "
   ```

2. **Test Pipeline**
   ```bash
   echo "Test text" | python3 cli/compression_advanced_cli.py test -p test
   ```

## Configuration

### Default Settings

The plugin comes pre-configured with optimal defaults:

- **Compression**: Balanced mode (40-50% savings)
- **Adaptive Eco**: Enabled
- **Semantic Scoring**: Enabled
- **Project Profiles**: Enabled
- **Cache Awareness**: Enabled

### Customizing Settings

Edit `.mcp.json` to customize (optional):

```bash
cd ~/.claude/plugins/ainl-graph-memory
# Edit .mcp.json with your preferences
```

See [docs/ADVANCED_COMPRESSION.md](docs/ADVANCED_COMPRESSION.md) for configuration options.

## Uninstalling

If you ever want to remove the plugin:

```bash
# Remove plugin directory
rm -rf ~/.claude/plugins/ainl-graph-memory

# Optional: Clean up project memory databases
# WARNING: This deletes all memory!
# find ~/.claude/projects -name "graph_memory" -type d -exec rm -rf {} +
```

## Next Steps

The plugin is **active and working**. Memory will accumulate automatically as you use Claude Code.

### Explore Your Memory

```bash
# View recent episodes
python3 cli/memory_cli.py list --type episode

# Search for something
python3 cli/memory_cli.py search "authentication"

# View learned patterns
python3 cli/memory_cli.py list --type procedural

# Check persona traits
python3 cli/memory_cli.py list --type persona
```

### Monitor Compression

```bash
# View compression stats
python3 cli/compression_advanced_cli.py adaptive
python3 cli/compression_advanced_cli.py quality

# Check project profile
python3 cli/compression_advanced_cli.py profile -p your-project-id
```

### Read Documentation

- [README.md](README.md) - Overview and quick start
- [docs/ADVANCED_COMPRESSION.md](docs/ADVANCED_COMPRESSION.md) - Advanced compression features
- [docs/AINL_CONCEPTS.md](docs/AINL_CONCEPTS.md) - Core AINL concepts
- [docs/COMPRESSION_ECO_MODE.md](docs/COMPRESSION_ECO_MODE.md) - Compression algorithms

## Support

- Issues: https://github.com/claude-code/ainl-graph-memory/issues
- Inspired by: [ArmaraOS AINL](https://github.com/sbhooley/armaraos)

---

**Plugin Status: ✅ ACTIVE**

The plugin will automatically load on every Claude Code startup.
Memory persists across sessions in `~/.claude/projects/[project-hash]/graph_memory/`
