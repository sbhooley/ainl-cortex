#!/bin/bash
# Quick live status check - run this during a Claude Code session

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}AINL Graph Memory - Live Status${NC}"
echo "=================================="
echo ""

# Find most recent project
PROJECT_DIR=$(ls -dt ~/.claude/projects/*-Users-clawdbot 2>/dev/null | head -1)

if [ -z "$PROJECT_DIR" ]; then
    echo -e "${YELLOW}⚠${NC} No active project found"
    exit 0
fi

PROJECT_NAME=$(basename "$PROJECT_DIR")
echo -e "Project: ${BLUE}$PROJECT_NAME${NC}"
echo ""

# Check memory databases
echo "Memory Status:"
if [ -d "$PROJECT_DIR/graph_memory" ]; then
    DB_FILES=$(find "$PROJECT_DIR/graph_memory" -name "*.db" 2>/dev/null)
    if [ -n "$DB_FILES" ]; then
        echo -e "  ${GREEN}✓${NC} Memory active"
        echo "$DB_FILES" | while read -r db; do
            SIZE=$(du -h "$db" | cut -f1)
            echo "    • $(basename "$db"): $SIZE"
        done
    else
        echo -e "  ${YELLOW}○${NC} No databases yet"
    fi
else
    echo -e "  ${YELLOW}○${NC} Memory not initialized"
fi
echo ""

# Check hook activity
echo "Hook Activity:"
HOOK_LOG=~/.claude/plugins/ainl-graph-memory/logs/hooks.log
if [ -f "$HOOK_LOG" ]; then
    LAST_ACTIVITY=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "$HOOK_LOG" 2>/dev/null || stat -c "%y" "$HOOK_LOG" 2>/dev/null | cut -d. -f1)
    ERROR_COUNT=$(tail -50 "$HOOK_LOG" 2>/dev/null | grep -c "ERROR" || echo "0")

    if [ $ERROR_COUNT -eq 0 ]; then
        echo -e "  ${GREEN}✓${NC} Hooks running cleanly"
    else
        echo -e "  ${YELLOW}⚠${NC} $ERROR_COUNT recent errors"
    fi
    echo "    Last activity: $LAST_ACTIVITY"
else
    echo -e "  ${YELLOW}○${NC} No hook logs yet"
fi
echo ""

# Check compression
echo "Compression:"
if [ -d "$PROJECT_DIR/compression_profiles" ]; then
    PROFILES=$(find "$PROJECT_DIR/compression_profiles" -name "*.json" 2>/dev/null | wc -l)
    echo -e "  ${GREEN}✓${NC} Active ($PROFILES profiles)"
else
    echo -e "  ${YELLOW}○${NC} Not yet configured"
fi
echo ""

# Check current session
echo "Current Session:"
SESSION_FILE=$(ls -t "$PROJECT_DIR"/*.jsonl 2>/dev/null | head -1)
if [ -n "$SESSION_FILE" ]; then
    SESSION_SIZE=$(du -h "$SESSION_FILE" | cut -f1)
    LINE_COUNT=$(wc -l < "$SESSION_FILE")
    echo -e "  ${GREEN}✓${NC} Active session"
    echo "    File: $(basename "$SESSION_FILE")"
    echo "    Size: $SESSION_SIZE"
    echo "    Events: $LINE_COUNT"
else
    echo -e "  ${YELLOW}○${NC} No active session"
fi
echo ""

# Show recent trajectories if any
if [ -d "$PROJECT_DIR/graph_memory" ] && [ -f "$PROJECT_DIR/graph_memory/trajectories.db" ]; then
    echo "Recent Trajectories:"
    sqlite3 "$PROJECT_DIR/graph_memory/trajectories.db" "SELECT COUNT(*) FROM trajectories" 2>/dev/null && \
        echo -e "  ${GREEN}✓${NC} $(sqlite3 "$PROJECT_DIR/graph_memory/trajectories.db" "SELECT COUNT(*) FROM trajectories") captured" || \
        echo -e "  ${YELLOW}○${NC} No trajectories yet"
    echo ""
fi

# Token savings estimate (if we have session data)
if [ -n "$SESSION_FILE" ] && [ -f "$SESSION_FILE" ]; then
    echo "Estimated Token Usage:"
    # This is a rough estimate based on file size
    CHARS=$(wc -c < "$SESSION_FILE")
    TOKENS=$((CHARS / 4))  # Rough estimate: 4 chars per token

    echo "  Current session: ~$TOKENS tokens"

    if [ -d "$PROJECT_DIR/compression_profiles" ]; then
        SAVED=$((TOKENS * 45 / 100))  # 45% savings estimate
        echo -e "  ${GREEN}Potential savings: ~$SAVED tokens (45%)${NC}"
    fi
fi

echo ""
echo "=================================="
echo "Run ~/.claude/plugins/ainl-graph-memory/verify_plugin_activation.sh"
echo "for full diagnostic report"
