#!/usr/bin/env bash
# verify_plugin_activation.sh — Post-install verification for AINL Cortex.
# Run after setup.sh + restarting Claude Code to confirm everything is wired up.
# Usage: bash scripts/verify_plugin_activation.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$PLUGIN_DIR/.venv/bin/python"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASS=0; FAIL=0

ok()   { echo -e "  ${GREEN}✓ PASS${NC} - $1"; PASS=$((PASS + 1)); }
fail() { echo -e "  ${RED}✗ FAIL${NC} - $1"; FAIL=$((FAIL + 1)); }
info() { echo "       $1"; }

echo ""
echo -e "${BLUE}=== AINL Cortex — Plugin Verification ===${NC}"
echo ""

# 1. Plugin directory
echo -e "${YELLOW}[1/10] Plugin directory${NC}"
if [ -d "$PLUGIN_DIR" ]; then
  ok "Found at $PLUGIN_DIR"
else
  fail "Not found — did setup.sh run from the right location?"
fi

# 2. Python venv
echo -e "${YELLOW}[2/10] Python venv${NC}"
if [ -x "$PYTHON" ]; then
  ok "$("$PYTHON" --version 2>&1)"
else
  fail ".venv not found — run: bash $PLUGIN_DIR/setup.sh"
fi

# 3. Core dependencies
echo -e "${YELLOW}[3/10] Python dependencies${NC}"
if "$PYTHON" -c "import mcp; from compiler_v2 import AICodeCompiler" 2>/dev/null; then
  ok "mcp + ainativelang (compiler_v2) importable"
else
  fail "Missing packages — run: $PYTHON -m pip install -r $PLUGIN_DIR/requirements-ainl.txt"
fi

# 4. Plugin identity
echo -e "${YELLOW}[4/10] Plugin identity (plugin.json)${NC}"
PLUGIN_JSON="$PLUGIN_DIR/.claude-plugin/plugin.json"
if [ -f "$PLUGIN_JSON" ]; then
  NAME=$("$PYTHON" -c "import json; d=json.load(open('$PLUGIN_JSON')); print(d['name'])")
  if [ "$NAME" = "ainl-cortex" ]; then
    ok "name = ainl-cortex"
  else
    fail "name = '$NAME' (expected ainl-cortex)"
  fi
else
  fail "plugin.json missing"
fi

# 5. MCP config
echo -e "${YELLOW}[5/10] MCP config (.mcp.json)${NC}"
MCP_JSON="$PLUGIN_DIR/.mcp.json"
if [ -f "$MCP_JSON" ]; then
  KEY=$("$PYTHON" -c "import json; d=json.load(open('$MCP_JSON')); print(list(d.keys())[0])")
  if [ "$KEY" = "ainl-cortex" ]; then
    ok "server key = ainl-cortex"
  else
    fail "server key = '$KEY' (expected ainl-cortex)"
  fi
else
  fail ".mcp.json missing"
fi

# 6. settings.json registration
echo -e "${YELLOW}[6/10] Claude Code registration (settings.json)${NC}"
SETTINGS="$HOME/.claude/settings.json"
if [ -f "$SETTINGS" ] && "$PYTHON" -c "
import json, sys
s = json.load(open('$SETTINGS'))
sys.exit(0 if 'ainl-cortex@ainl-local' in s.get('enabledPlugins', {}) else 1)
" 2>/dev/null; then
  ok "ainl-cortex@ainl-local registered"
else
  fail "Plugin not registered — run: bash $PLUGIN_DIR/setup.sh"
fi

# 7. Marketplace symlink
echo -e "${YELLOW}[7/10] Marketplace symlink${NC}"
LINK="$HOME/.claude/ainl-local-marketplace/plugins/ainl-cortex"
if [ -L "$LINK" ] || [ -d "$LINK" ]; then
  ok "Symlink present"
else
  fail "Symlink missing — run: bash $PLUGIN_DIR/setup.sh"
fi

# 8. Hook scripts
echo -e "${YELLOW}[8/10] Hook scripts${NC}"
HOOK_COUNT=0
for f in "$PLUGIN_DIR/hooks/"*.py; do
  [ -x "$f" ] && ((HOOK_COUNT++)) || true
done
if [ "$HOOK_COUNT" -ge 6 ]; then
  ok "$HOOK_COUNT executable hook scripts"
else
  fail "Only $HOOK_COUNT executable hooks (expected ≥6) — run: chmod +x $PLUGIN_DIR/hooks/*.py"
fi

# 9. Compression profiles directory (plugin-level, not project-level)
echo -e "${YELLOW}[9/10] Compression profiles${NC}"
PROFILES_DIR="$PLUGIN_DIR/profiles"
if [ -d "$PROFILES_DIR" ]; then
  COUNT=$(find "$PROFILES_DIR" -name "*.json" 2>/dev/null | wc -l | tr -d ' ')
  ok "profiles/ exists ($COUNT profile files)"
else
  ok "profiles/ not yet created (created on first compression — normal for new installs)"
fi

# 10. MCP server imports
echo -e "${YELLOW}[10/10] MCP server modules${NC}"
if "$PYTHON" -c "
import sys; sys.path.insert(0, '$PLUGIN_DIR')
from mcp_server.graph_store import get_graph_store
from mcp_server.ainl_tools import AINLTools
from mcp_server.a2a_tools import A2ATools
from mcp_server.goal_tracker import GoalTracker
from mcp_server.config import get_config
" 2>/dev/null; then
  ok "All server modules importable"
else
  fail "Server import failed — check: $PLUGIN_DIR/logs/mcp_server.log"
fi

# Memory databases (informational, not pass/fail — new installs have none yet)
echo ""
echo "  Memory databases (informational):"
DB_COUNT=$(find "$HOME/.claude/projects" -name "ainl_memory.db" -o -name "ainl_native.db" 2>/dev/null | wc -l | tr -d ' ')
if [ "$DB_COUNT" -gt 0 ]; then
  echo "  Found $DB_COUNT database(s) across projects:"
  find "$HOME/.claude/projects" -name "ainl_memory.db" -o -name "ainl_native.db" 2>/dev/null | while read -r db; do
    SIZE=$(du -h "$db" 2>/dev/null | cut -f1)
    echo "    • $db ($SIZE)"
  done
else
  echo "  None yet — created on first interaction (normal for new installs)"
fi

# Hook logs (informational)
HOOK_LOG="$PLUGIN_DIR/logs/hooks.log"
echo ""
echo "  Hook log (last 3 lines):"
if [ -f "$HOOK_LOG" ]; then
  tail -3 "$HOOK_LOG" | sed 's/^/    /'
else
  echo "    No log yet — hooks fire on first session after restart"
fi

# Summary
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "  Passed: ${GREEN}$PASS${NC} / $((PASS + FAIL))"
echo -e "${BLUE}========================================${NC}"
echo ""
if [ "$FAIL" -eq 0 ]; then
  echo -e "  ${GREEN}✓ All checks passed.${NC}"
  echo ""
  echo "  Next: restart Claude Code, then run /mcp to confirm ~24 ainl-cortex__ tools."
  echo ""
  echo "  After a few interactions you should see:"
  echo "    • Memory databases growing in ~/.claude/projects/*/graph_memory/"
  echo "    • Hook activity in $PLUGIN_DIR/logs/hooks.log"
elif [ "$FAIL" -le 2 ]; then
  echo -e "  ${YELLOW}⚠ $FAIL check(s) failed — likely normal before first use.${NC}"
  echo ""
  echo "  Recommended:"
  echo "    1. Restart Claude Code"
  echo "    2. Use it for a few interactions"
  echo "    3. Run this script again"
  echo ""
else
  echo -e "  ${RED}✗ $FAIL check(s) failed. Fix the above, then re-run.${NC}"
  echo ""
  echo "  Quick fixes:"
  echo "    • Missing venv/packages: bash $PLUGIN_DIR/setup.sh"
  echo "    • Hooks not executable: chmod +x $PLUGIN_DIR/hooks/*.py"
  echo "    • Server logs: tail -50 $PLUGIN_DIR/logs/mcp_server.log"
fi
echo ""
