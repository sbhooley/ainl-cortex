#!/usr/bin/env bash
# verify_activation.sh — Quick post-install check for AINL Cortex.
# Run immediately after setup.sh to confirm the plugin is wired up correctly.
# Usage: bash scripts/verify_activation.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$PLUGIN_DIR/.venv/bin/python"
PASS=0; FAIL=0

ok()   { echo "  ✅ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ❌ $1"; FAIL=$((FAIL + 1)); }
info() { echo "     $1"; }

echo ""
echo "=== AINL Cortex — Activation Check ==="
echo ""

# 1. Plugin dir
echo "[1] Plugin directory"
if [ -d "$PLUGIN_DIR" ]; then
  ok "Found at $PLUGIN_DIR"
else
  fail "Not found — did setup.sh run from the right location?"
fi

# 2. Venv
echo "[2] Python venv"
if [ -x "$PYTHON" ]; then
  ok "$("$PYTHON" --version 2>&1)"
else
  fail ".venv not found — run: bash $PLUGIN_DIR/setup.sh"
fi

# 3. Core dependencies
echo "[3] Dependencies"
if "$PYTHON" -c "import mcp; from compiler_v2 import AICodeCompiler" 2>/dev/null; then
  ok "mcp + ainativelang (compiler_v2) importable"
else
  fail "Missing packages — run: $PYTHON -m pip install -r $PLUGIN_DIR/requirements-ainl.txt"
fi

# 4. Plugin identity
echo "[4] Plugin identity (plugin.json)"
if [ -f "$PLUGIN_DIR/.claude-plugin/plugin.json" ]; then
  NAME=$("$PYTHON" -c "import json; d=json.load(open('$PLUGIN_DIR/.claude-plugin/plugin.json')); print(d['name'])")
  if [ "$NAME" = "ainl-cortex" ]; then
    ok "name = ainl-cortex"
  else
    fail "name = '$NAME' (expected ainl-cortex)"
  fi
else
  fail "plugin.json missing"
fi

# 5. MCP server config
echo "[5] MCP config (.mcp.json)"
if [ -f "$PLUGIN_DIR/.mcp.json" ]; then
  KEY=$("$PYTHON" -c "import json; d=json.load(open('$PLUGIN_DIR/.mcp.json')); print(list(d.keys())[0])")
  if [ "$KEY" = "ainl-cortex" ]; then
    ok "server key = ainl-cortex"
  else
    fail "server key = '$KEY' (expected ainl-cortex)"
  fi
else
  fail ".mcp.json missing"
fi

# 6. settings.json registration
echo "[6] Claude Code registration (settings.json)"
SETTINGS="$HOME/.claude/settings.json"
if [ -f "$SETTINGS" ] && "$PYTHON" -c "
import json, sys
s = json.load(open('$SETTINGS'))
enabled = s.get('enabledPlugins', {})
sys.exit(0 if 'ainl-cortex@ainl-local' in enabled else 1)
" 2>/dev/null; then
  ok "ainl-cortex@ainl-local = true"
else
  fail "Plugin not registered — run: bash $PLUGIN_DIR/setup.sh"
fi

# 7. Marketplace symlink
echo "[7] Marketplace symlink"
MARKETPLACE="$HOME/.claude/ainl-local-marketplace"
if [ -L "$MARKETPLACE/plugins/ainl-cortex" ] || [ -d "$MARKETPLACE/plugins/ainl-cortex" ]; then
  ok "Symlink present"
else
  fail "Symlink missing — run: bash $PLUGIN_DIR/setup.sh"
fi

# 8. Hooks
echo "[8] Hook scripts"
HOOK_COUNT=0
for f in "$PLUGIN_DIR/hooks/"*.py; do
  [ -x "$f" ] && ((HOOK_COUNT++)) || true
done
if [ "$HOOK_COUNT" -ge 6 ]; then
  ok "$HOOK_COUNT executable hook scripts"
else
  fail "Only $HOOK_COUNT executable hooks (expected ≥6) — run: chmod +x $PLUGIN_DIR/hooks/*.py"
fi

# 9. Config loads
echo "[9] Config"
if "$PYTHON" -c "
import sys; sys.path.insert(0, '$PLUGIN_DIR')
from mcp_server.config import get_config
c = get_config()
assert c.is_compression_enabled() is not None
" 2>/dev/null; then
  ok "Config loads cleanly"
else
  fail "Config failed to load — check $PLUGIN_DIR/config.json"
fi

# 10. MCP server imports
echo "[10] MCP server"
if "$PYTHON" -c "
import sys; sys.path.insert(0, '$PLUGIN_DIR')
from mcp_server.graph_store import get_graph_store
from mcp_server.ainl_tools import AINLTools
from mcp_server.a2a_tools import A2ATools
from mcp_server.goal_tracker import GoalTracker
" 2>/dev/null; then
  ok "All server modules importable"
else
  fail "Server import failed — check logs: $PLUGIN_DIR/logs/mcp_server.log"
fi

# Summary
echo ""
echo "  Passed: $PASS / $((PASS + FAIL))"
echo ""
if [ "$FAIL" -eq 0 ]; then
  echo "  ✅ Ready — restart Claude Code and run /mcp to confirm ~24 tools."
else
  echo "  ❌ $FAIL check(s) failed. Fix the above, then re-run this script."
fi
echo ""
