#!/usr/bin/env bash
# check_live_status.sh — Quick live status during a Claude Code session.
# Usage: bash scripts/check_live_status.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$PLUGIN_DIR/.venv/bin/python"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo ""
echo -e "${BLUE}=== AINL Cortex — Live Status ===${NC}"
echo ""

# ── Plugin backend ─────────────────────────────────────────────────────────
echo "Plugin:"
echo "  Dir:     $PLUGIN_DIR"
if [ -x "$PYTHON" ]; then
  BACKEND=$("$PYTHON" -c "
import json, pathlib
cfg = json.load(open('$PLUGIN_DIR/config.json'))
print(cfg.get('memory', {}).get('store_backend', 'python'))
" 2>/dev/null || echo "unknown")
  echo "  Backend: $BACKEND"
  echo -e "  Venv:    ${GREEN}ok${NC}"
else
  echo -e "  Venv:    ${RED}missing${NC} — run: bash $PLUGIN_DIR/setup.sh"
fi
echo ""

# ── Memory databases ────────────────────────────────────────────────────────
echo "Memory Databases:"
DB_LIST=$(find "$HOME/.claude/projects" -name "ainl_memory.db" -o -name "ainl_native.db" 2>/dev/null)
if [ -n "$DB_LIST" ]; then
  echo "$DB_LIST" | while read -r db; do
    SIZE=$(du -h "$db" 2>/dev/null | cut -f1)
    PROJECT=$(basename "$(dirname "$(dirname "$db")")")
    echo -e "  ${GREEN}✓${NC} $PROJECT/graph_memory/$(basename "$db")  ($SIZE)"
  done
else
  echo -e "  ${YELLOW}○${NC} None yet — created on first interaction"
fi
echo ""

# ── Trajectories ────────────────────────────────────────────────────────────
TRAJ_DBS=$(find "$HOME/.claude/projects" -name "ainl_trajectories.db" 2>/dev/null)
if [ -n "$TRAJ_DBS" ]; then
  echo "Trajectories:"
  echo "$TRAJ_DBS" | while read -r db; do
    COUNT=$(sqlite3 "$db" "SELECT COUNT(*) FROM trajectories" 2>/dev/null || echo "?")
    PROJECT=$(basename "$(dirname "$(dirname "$db")")")
    echo -e "  ${GREEN}✓${NC} $PROJECT: $COUNT captured"
  done
  echo ""
fi

# ── Compression profiles ────────────────────────────────────────────────────
echo "Compression Profiles:"
PROFILES_DIR="$PLUGIN_DIR/profiles"
if [ -d "$PROFILES_DIR" ]; then
  COUNT=$(find "$PROFILES_DIR" -name "*.json" 2>/dev/null | wc -l | tr -d ' ')
  echo -e "  ${GREEN}✓${NC} $COUNT profile(s) in $PROFILES_DIR"
  find "$PROFILES_DIR" -name "*.json" 2>/dev/null | while read -r p; do
    echo "    • $(basename "$p")"
  done
else
  echo -e "  ${YELLOW}○${NC} Not yet created (built on first compression)"
fi
echo ""

# ── Hook activity ───────────────────────────────────────────────────────────
echo "Hook Activity:"
HOOK_LOG="$PLUGIN_DIR/logs/hooks.log"
if [ -f "$HOOK_LOG" ]; then
  LAST=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "$HOOK_LOG" 2>/dev/null \
      || stat -c "%y" "$HOOK_LOG" 2>/dev/null | cut -d. -f1)
  ERRORS=$(tail -50 "$HOOK_LOG" 2>/dev/null | grep -c "ERROR" || echo "0")
  if [ "$ERRORS" -eq 0 ]; then
    echo -e "  ${GREEN}✓${NC} Running cleanly"
  else
    echo -e "  ${YELLOW}⚠${NC} $ERRORS recent error(s)"
  fi
  echo "    Last activity: $LAST"
  echo "  Recent (last 3 lines):"
  tail -3 "$HOOK_LOG" | sed 's/^/    /'
else
  echo -e "  ${YELLOW}○${NC} No log yet — hooks fire after first session post-restart"
fi
echo ""

# ── Inbox (buffered captures) ───────────────────────────────────────────────
INBOX_DIR="$PLUGIN_DIR/inbox"
if [ -d "$INBOX_DIR" ]; then
  PENDING=$(find "$INBOX_DIR" -name "*.jsonl" -exec wc -l {} \; 2>/dev/null \
    | awk '{sum += $1} END {print sum+0}')
  if [ "$PENDING" -gt 0 ]; then
    echo -e "Inbox: ${YELLOW}$PENDING pending capture(s)${NC} (will drain on next MCP query)"
  else
    echo -e "Inbox: ${GREEN}✓ empty${NC} (all captures drained)"
  fi
  echo ""
fi

# ── MCP server registration ─────────────────────────────────────────────────
echo "Registration:"
SETTINGS="$HOME/.claude/settings.json"
if [ -f "$SETTINGS" ] && grep -q "ainl-cortex@ainl-local" "$SETTINGS" 2>/dev/null; then
  echo -e "  ${GREEN}✓${NC} ainl-cortex@ainl-local registered in settings.json"
else
  echo -e "  ${RED}✗${NC} Not registered — run: bash $PLUGIN_DIR/setup.sh"
fi

LINK="$HOME/.claude/ainl-local-marketplace/plugins/ainl-cortex"
if [ -L "$LINK" ] || [ -d "$LINK" ]; then
  echo -e "  ${GREEN}✓${NC} Marketplace symlink present"
else
  echo -e "  ${RED}✗${NC} Marketplace symlink missing — run: bash $PLUGIN_DIR/setup.sh"
fi
echo ""

echo "=================================="
echo "Full diagnostic: bash $PLUGIN_DIR/scripts/verify_plugin_activation.sh"
echo ""
