#!/bin/bash
# AINL Graph Memory Plugin - Activation Verification Script
# Run this after restarting Claude Code to verify the plugin is working

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}AINL Graph Memory Plugin Verification${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Track overall status
TESTS_PASSED=0
TESTS_FAILED=0

# Function to print test result
test_result() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✓ PASS${NC} - $2"
        ((TESTS_PASSED++))
    else
        echo -e "${RED}✗ FAIL${NC} - $2"
        ((TESTS_FAILED++))
    fi
}

# Test 1: Check plugin directory exists
echo -e "${YELLOW}[1/10] Checking plugin installation...${NC}"
if [ -d ~/.claude/plugins/ainl-cortex ]; then
    test_result 0 "Plugin directory exists"
else
    test_result 1 "Plugin directory not found"
fi

# Test 2: Check MCP configuration
echo -e "${YELLOW}[2/10] Checking MCP configuration...${NC}"
if [ -f ~/.claude/plugins/ainl-cortex/.mcp.json ]; then
    test_result 0 "MCP configuration file exists"
else
    test_result 1 "MCP configuration file missing"
fi

# Test 3: Check settings.json has enableAllProjectMcpServers
echo -e "${YELLOW}[3/10] Checking Claude Code settings...${NC}"
if grep -q "enableAllProjectMcpServers" ~/.claude/settings.json 2>/dev/null; then
    test_result 0 "MCP servers enabled in settings"
else
    test_result 1 "MCP servers not enabled in settings"
fi

# Test 4: Check Python dependencies
echo -e "${YELLOW}[4/10] Checking Python dependencies...${NC}"
cd ~/.claude/plugins/ainl-cortex
if python3 -c "import sys; sys.path.insert(0, '.'); from mcp_server import compression_profiles" 2>/dev/null; then
    test_result 0 "Python dependencies available"
else
    test_result 1 "Python dependencies missing (run: pip install -r requirements.txt)"
fi

# Test 5: Check for project directory
echo -e "${YELLOW}[5/10] Checking project directories...${NC}"
PROJECT_DIR=$(ls -d ~/.claude/projects/*-Users-clawdbot 2>/dev/null | head -1)
if [ -n "$PROJECT_DIR" ]; then
    test_result 0 "Project directory found: $(basename "$PROJECT_DIR")"
    echo "   Location: $PROJECT_DIR"
else
    test_result 1 "No project directory found (will be created on first use)"
fi

# Test 6: Check for memory databases
echo -e "${YELLOW}[6/10] Checking memory databases...${NC}"
if [ -n "$PROJECT_DIR" ] && [ -d "$PROJECT_DIR/graph_memory" ]; then
    DB_COUNT=$(find "$PROJECT_DIR/graph_memory" -name "*.db" 2>/dev/null | wc -l)
    if [ $DB_COUNT -gt 0 ]; then
        test_result 0 "Memory databases exist ($DB_COUNT found)"
        find "$PROJECT_DIR/graph_memory" -name "*.db" -exec echo "   - {}" \;
    else
        test_result 1 "No memory databases yet (will be created on first interaction)"
    fi
else
    test_result 1 "No graph_memory directory yet (will be created on first interaction)"
fi

# Test 7: Check hook logs
echo -e "${YELLOW}[7/10] Checking hook execution logs...${NC}"
HOOK_LOG=~/.claude/plugins/ainl-cortex/logs/hooks.log
if [ -f "$HOOK_LOG" ]; then
    RECENT_LOGS=$(tail -20 "$HOOK_LOG" 2>/dev/null | grep -v "JSONDecodeError" | wc -l)
    if [ $RECENT_LOGS -gt 0 ]; then
        test_result 0 "Hooks are executing (check logs/hooks.log)"
    else
        ERROR_COUNT=$(tail -20 "$HOOK_LOG" 2>/dev/null | grep -c "ERROR" || echo "0")
        if [ $ERROR_COUNT -gt 0 ]; then
            test_result 1 "Hooks have errors (see logs/hooks.log)"
            echo "   Recent errors: $ERROR_COUNT"
        else
            test_result 1 "No recent hook activity (restart Claude Code if you just enabled)"
        fi
    fi
else
    test_result 1 "No hook logs yet (will be created on first hook execution)"
fi

# Test 8: Check compression profiles
echo -e "${YELLOW}[8/10] Checking compression system...${NC}"
if [ -n "$PROJECT_DIR" ] && [ -d "$PROJECT_DIR/compression_profiles" ]; then
    PROFILE_COUNT=$(find "$PROJECT_DIR/compression_profiles" -name "*.json" 2>/dev/null | wc -l)
    test_result 0 "Compression profiles directory exists ($PROFILE_COUNT profiles)"
else
    test_result 1 "No compression profiles yet (will be created on first use)"
fi

# Test 9: Test MCP server can start
echo -e "${YELLOW}[9/10] Testing MCP server executable...${NC}"
cd ~/.claude/plugins/ainl-cortex
if timeout 2 python3 mcp_server/server.py --help >/dev/null 2>&1; then
    test_result 0 "MCP server is executable"
else
    test_result 1 "MCP server failed to start (check dependencies)"
fi

# Test 10: Check for AINL tools availability (this requires Claude Code to be running)
echo -e "${YELLOW}[10/10] Checking AINL integration...${NC}"
if [ -f ~/.claude/plugins/ainl-cortex/mcp_server/ainl_tools.py ]; then
    test_result 0 "AINL tools module exists"
else
    test_result 1 "AINL tools module missing"
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "Tests passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Tests failed: ${RED}$TESTS_FAILED${NC}"
echo ""

# Provide recommendations based on results
if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All checks passed!${NC}"
    echo ""
    echo "The plugin appears to be properly configured."
    echo ""
    echo "Expected behavior after restart:"
    echo "  • Memory databases will be created on first interaction"
    echo "  • Hooks will capture tool usage automatically"
    echo "  • Compression will activate for context management"
    echo "  • Token savings will accumulate over time"
    echo ""
    echo "To verify it's working during a session:"
    echo "  1. Use Claude Code normally"
    echo "  2. Run: ls -la ~/.claude/projects/*/graph_memory/*.db"
    echo "  3. Check hook logs: tail -f logs/hooks.log"
    echo ""
elif [ $TESTS_FAILED -le 3 ]; then
    echo -e "${YELLOW}⚠ Some checks failed, but this may be normal before first use${NC}"
    echo ""
    echo "Common reasons:"
    echo "  • Plugin not used yet (databases created on first interaction)"
    echo "  • Claude Code needs restart to load MCP server"
    echo "  • Hooks will activate after restart"
    echo ""
    echo "Recommended actions:"
    echo "  1. Restart Claude Code"
    echo "  2. Use Claude Code normally for a few interactions"
    echo "  3. Run this script again to verify databases were created"
    echo ""
else
    echo -e "${RED}✗ Multiple issues detected${NC}"
    echo ""
    echo "Recommended fixes:"
    if grep -q "dependencies missing" <(echo "$TESTS_FAILED"); then
        echo "  • Install dependencies: cd ~/.claude/plugins/ainl-cortex && pip install -r requirements.txt"
    fi
    echo "  • Restart Claude Code to load the plugin"
    echo "  • Check Claude Code console for errors"
    echo "  • Review logs at ~/.claude/plugins/ainl-cortex/logs/"
    echo ""
fi

# Additional diagnostics
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Additional Diagnostics${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

echo "Plugin location:"
echo "  $(pwd)"
echo ""

echo "Python version:"
python3 --version || echo "  Python 3 not found"
echo ""

echo "Recent hook log (last 5 lines):"
if [ -f "$HOOK_LOG" ]; then
    tail -5 "$HOOK_LOG" | sed 's/^/  /'
else
    echo "  No log file yet"
fi
echo ""

echo "Settings check:"
if [ -f ~/.claude/settings.json ]; then
    echo "  enableAllProjectMcpServers: $(grep -o '"enableAllProjectMcpServers"[[:space:]]*:[[:space:]]*[^,}]*' ~/.claude/settings.json | cut -d: -f2 | tr -d ' ')"
else
    echo "  settings.json not found"
fi
echo ""

echo -e "${BLUE}========================================${NC}"
echo "Verification complete!"
echo ""
echo "For detailed status, run:"
echo "  cat /tmp/plugin_status_report.md"
echo ""
