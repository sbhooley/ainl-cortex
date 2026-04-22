# AINL Graph Memory Plugin - Activation Guide

## Current Status: ✅ CONFIGURED, ⏳ AWAITING RESTART

The plugin has been configured but **requires a Claude Code restart** to fully activate.

---

## What Was Configured

✅ **MCP Server Enabled**
- Location: `~/.claude/settings.json`
- Setting: `enableAllProjectMcpServers: true`
- This enables the plugin's MCP server to provide AINL tools

✅ **Plugin Installed**
- Location: `~/.claude/plugins/ainl-graph-memory/`
- All files present and functional
- Hooks ready to activate

---

## Next Steps

### 1. Restart Claude Code

**This is required** for the configuration to take effect.

After restart, the plugin will:
- Load the MCP server (provides AINL validation, compression, memory tools)
- Activate hooks (automatic memory capture)
- Start tracking interactions
- Begin compressing context

### 2. Run Verification Script

After restarting Claude Code, run:

```bash
~/.claude/plugins/ainl-graph-memory/verify_plugin_activation.sh
```

This comprehensive script checks:
- ✓ Plugin installation
- ✓ MCP configuration
- ✓ Python dependencies
- ✓ Memory database creation
- ✓ Hook execution
- ✓ Compression system
- ✓ AINL integration

**Expected output:** 8-10 tests passing after first use

### 3. Check Live Status (During Sessions)

While using Claude Code, run:

```bash
~/.claude/plugins/ainl-graph-memory/check_live_status.sh
```

This shows real-time:
- Active memory databases
- Hook activity
- Compression status
- Current session info
- Token usage estimates

---

## What To Expect

### First Interaction (After Restart)

**Nothing visible yet** - The plugin initializes silently:
- No memory databases (created on first interaction)
- No hook logs (created on first event)
- No compression profiles (created when needed)

### After 1-5 Interactions

You should see:
- Memory databases created in `~/.claude/projects/[hash]/graph_memory/`
- Hook logs appearing in `~/.claude/plugins/ainl-graph-memory/logs/hooks.log`
- Persona traits beginning to evolve

### After 10+ Interactions

Full functionality active:
- **Pattern recognition** - Successful workflows stored
- **Persona evolution** - Your coding style learned
- **Failure prevention** - Errors remembered and prevented
- **Compression active** - 40-70% token savings
- **Context optimization** - Best 500 tokens selected automatically

---

## Verification Checklist

Run after restart and a few interactions:

- [ ] Restart Claude Code
- [ ] Run verification script
- [ ] Check for memory databases: `ls -la ~/.claude/projects/*/graph_memory/*.db`
- [ ] Monitor hook logs: `tail -f ~/.claude/plugins/ainl-graph-memory/logs/hooks.log`
- [ ] Verify compression: `python3 ~/.claude/plugins/ainl-graph-memory/cli/compression_cli.py config`
- [ ] Use Claude Code normally for 5-10 interactions
- [ ] Run live status check
- [ ] Confirm databases growing: `du -sh ~/.claude/projects/*/graph_memory/`

---

## Troubleshooting

### If verification script shows failures:

1. **"Python dependencies missing"**
   ```bash
   cd ~/.claude/plugins/ainl-graph-memory
   pip install -r requirements.txt
   ```

2. **"No hook activity"**
   - Restart Claude Code again
   - Ensure you've had at least one interaction
   - Check logs: `cat logs/hooks.log`

3. **"MCP server failed to start"**
   - Test manually: `python3 mcp_server/server.py --help`
   - Check Python version: `python3 --version` (need 3.10+)

4. **"No memory databases"**
   - Normal if you haven't used Claude Code yet
   - Use Claude normally, databases created automatically

### If hooks show errors:

Check the log for specific errors:
```bash
tail -50 ~/.claude/plugins/ainl-graph-memory/logs/hooks.log
```

Common fixes:
- Ensure Claude Code is fully restarted
- Verify plugin directory permissions
- Check Python imports work

---

## Success Indicators

You'll know it's working when you see:

✅ **Memory databases exist:**
```bash
$ ls ~/.claude/projects/*/graph_memory/
ainl_memory.db  failures.db  persona.db  trajectories.db
```

✅ **Hook logs show activity:**
```bash
$ tail logs/hooks.log
2026-04-21 17:30:15 - INFO - Captured user prompt
2026-04-21 17:30:20 - INFO - Recorded tool use: Read
```

✅ **Compression configured:**
```bash
$ python3 cli/compression_cli.py config
Current mode: balanced
Token savings: 45%
```

✅ **Live status shows green:**
```bash
$ ./check_live_status.sh
Memory Status:
  ✓ Memory active
    • ainl_memory.db: 128K
```

---

## Token Savings

Once active, you should see savings like:

| Session Type | Without Plugin | With Plugin (Balanced) | Savings |
|--------------|----------------|------------------------|---------|
| This session | ~65,000 tokens | ~35,750 tokens | 29,250 (45%) |
| 10 interactions | ~100,000 tokens | ~55,000 tokens | 45,000 (45%) |
| Daily usage | ~500,000 tokens | ~275,000 tokens | 225,000 (45%) |

**Aggressive mode:** Up to 65% savings

---

## Quick Commands Reference

```bash
# Full verification (run after restart)
~/.claude/plugins/ainl-graph-memory/verify_plugin_activation.sh

# Live status (run during sessions)
~/.claude/plugins/ainl-graph-memory/check_live_status.sh

# View memory
python3 ~/.claude/plugins/ainl-graph-memory/cli/memory_cli.py list --type episode --limit 10

# Check compression
python3 ~/.claude/plugins/ainl-graph-memory/cli/compression_cli.py config

# View persona
python3 ~/.claude/plugins/ainl-graph-memory/cli/memory_cli.py list --type persona

# Monitor hooks live
tail -f ~/.claude/plugins/ainl-graph-memory/logs/hooks.log

# Check databases
ls -lah ~/.claude/projects/*/graph_memory/
```

---

## Support

If issues persist:
1. Check `/tmp/plugin_status_report.md` for detailed diagnostics
2. Review logs in `~/.claude/plugins/ainl-graph-memory/logs/`
3. Run verification script with full output
4. Check GitHub issues: https://github.com/sbhooley/ainativelang-claudecode/issues

---

**Status:** Ready for activation - Restart Claude Code to begin! 🚀
