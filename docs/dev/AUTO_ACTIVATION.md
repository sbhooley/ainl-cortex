# AINL Graph Memory - Auto-Activation Guide

## ✅ Auto-Activation Configured

This plugin is now configured to **automatically activate** every time you start Claude Code.

## Visual Startup Indicator

When Claude Code starts, you will see this banner:

```
╔═══════════════════════════════════════════════════════════╗
║  🧠 AINL GRAPH MEMORY - ACTIVE                            ║
╚═══════════════════════════════════════════════════════════╝

  Status: ✅ READY
  Mode: AGGRESSIVE
  Token Savings: ~78%

  MCP Server: Running
  Compression: ON
  Database: Project-specific memory active

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

This confirms:
- ✅ Plugin is active
- ✅ Compression mode (AGGRESSIVE = ~78% token savings)
- ✅ MCP server is running
- ✅ Project-specific memory database is connected

## What Happens Automatically

### On Every Claude Code Startup:

1. **SessionStart Hook** executes
2. **Visual banner** displays in terminal
3. **MCP Server** launches automatically
4. **Compression** activates immediately
5. **Memory system** connects to project database
6. **All hooks** are ready:
   - PreCompact (compression prep)
   - PostCompact (tracking savings)
   - PostToolUse (memory capture)
   - UserPromptSubmit (prompt processing)
   - UserPromptExpansion (context expansion)

## Current Configuration

### Compression Settings
- **Mode:** AGGRESSIVE
- **Token Savings:** ~78% reduction
- **Semantic Scoring:** Enabled
- **Adaptive Eco:** Enabled
- **Cache Awareness:** Enabled

### MCP Server
- **Server:** ainl-graph-memory
- **Status:** Auto-start enabled
- **Database:** Project-specific (per working directory)
- **Tools:** 7 memory tools available

### Hooks
All hooks configured in `~/.claude/settings.json`:
- ✅ SessionStart (startup banner)
- ✅ UserPromptSubmit
- ✅ UserPromptExpansion
- ✅ PostToolUse
- ✅ PreCompact
- ✅ PostCompact
- ✅ Stop

## Verification

To verify the plugin is active:

1. Look for the startup banner when Claude Code launches
2. Check logs: `tail -f ~/.claude/plugins/ainl-graph-memory/logs/hooks.log`
3. Verify compression: Sessions should show reduced token usage

## Configuration Files

- **Settings:** `~/.claude/settings.json`
- **Compression:** `~/.claude/plugins/ainl-graph-memory/config.json`
- **MCP Config:** `~/.claude/plugins/ainl-graph-memory/.mcp.json`
- **Hooks:** `~/.claude/plugins/ainl-graph-memory/hooks/`

## Changing Compression Mode

To switch compression modes, edit `config.json`:

```json
{
  "compression": {
    "mode": "aggressive"  // or "balanced" or "off"
  }
}
```

Modes:
- **aggressive:** ~78% token savings (maximum compression)
- **balanced:** ~63% token savings (quality vs compression)
- **off:** No compression

## Troubleshooting

### Banner doesn't appear
- Check `~/.claude/settings.json` has SessionStart hook
- Verify hook script is executable: `ls -la hooks/startup.py`
- Check logs: `tail -f logs/hooks.log`

### Compression not working
- Verify `config.json` has `"enabled": true`
- Check compression mode is not "off"
- Review logs: `tail -f logs/mcp_server.log`

### MCP server not starting
- Check `.venv` exists and has dependencies
- Run test: `cd ~/.claude/plugins/ainl-graph-memory && .venv/bin/python -m mcp_server.server`
- Verify `.mcp.json` configuration

## Support

Plugin Location: `~/.claude/plugins/ainl-graph-memory/`

For issues:
1. Check logs in `logs/` directory
2. Run verification: `./verify_plugin_activation.sh`
3. Test compression: `.venv/bin/python test_compression.py`
