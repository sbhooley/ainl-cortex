#!/usr/bin/env bash
# bug_hunt_matrix.sh — Regression matrix for install / native upgrade / MCP packaging.
#
# Usage:
#   bash scripts/bug_hunt_matrix.sh           # run all scenarios (non-destructive)
#   bash scripts/bug_hunt_matrix.sh --quick # smoke + import paths only
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PLUGIN_DIR}/.venv/bin/python"
QUICK=false
PASS=0
FAIL=0

while [ $# -gt 0 ]; do
  case "$1" in
    --quick) QUICK=true ;;
    -h|--help)
      sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown: $1" >&2; exit 2 ;;
  esac
  shift
done

ok()   { echo "  ✅ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ❌ $1"; FAIL=$((FAIL + 1)); }

echo ""
echo "=== AINL Cortex — Bug hunt matrix ==="
echo "  Plugin: $PLUGIN_DIR"
echo ""

# [1] Python backend default
echo "[1] config store_backend default / valid"
BACKEND=$("$PYTHON" -c "import json; print(json.load(open('$PLUGIN_DIR/config.json'))['memory'].get('store_backend',''))")
if [ "$BACKEND" = "python" ] || [ "$BACKEND" = "native" ]; then
  ok "store_backend=$BACKEND"
else
  fail "unexpected store_backend=$BACKEND"
fi

# [2] Package-mode MCP import
echo "[2] MCP package-mode import"
if "$PYTHON" -c "
import sys, logging
logging.disable(logging.CRITICAL)
sys.path.insert(0, '$PLUGIN_DIR')
import mcp_server.server
" 2>/dev/null; then
  ok "mcp_server.server imports"
else
  fail "package-mode import"
fi

# [3] Live memory_store_failure (no mcp_server/ on PYTHONPATH)
echo "[3] memory_store_failure (live path)"
if PLUGIN_DIR="$PLUGIN_DIR" "$PYTHON" <<'PY' 2>/dev/null
import asyncio, logging, os, sys, tempfile
from pathlib import Path
logging.disable(logging.CRITICAL)
ROOT = Path(os.environ["PLUGIN_DIR"])
sys.path.insert(0, str(ROOT))
if str(ROOT / "mcp_server") in sys.path:
    sys.path.remove(str(ROOT / "mcp_server"))
import mcp_server.server as srv
from mcp_server.graph_store import SQLiteGraphStore

async def main():
    db = Path(tempfile.mktemp(suffix=".db"))
    srv.memory_server.store = SQLiteGraphStore(db)
    r = await srv.memory_store_failure(
        project_id="bug-hunt",
        error_type="test",
        tool="test",
        error_message="matrix",
    )
    assert "node_id" in r and "error" not in r, r

asyncio.run(main())
PY
then
  ok "memory_store_failure"
else
  fail "memory_store_failure"
fi

# [4] ainl_native import (optional)
echo "[4] ainl_native wheel"
if "$PYTHON" -c "import ainl_native" 2>/dev/null; then
  ok "ainl_native importable"
else
  echo "     (skip — wheel not installed; Python backend still valid)"
  ok "ainl_native optional skip"
fi

# [5] upgrade scripts + runbook
echo "[5] native upgrade runbook"
if [ -x "$PLUGIN_DIR/scripts/upgrade_to_native.sh" ] && [ -x "$PLUGIN_DIR/scripts/claude_do_native_upgrade.sh" ]; then
  if "$PYTHON" "$PLUGIN_DIR/scripts/native_upgrade_status.py" --json >/dev/null 2>&1; then
    ok "upgrade scripts + status JSON"
  else
    fail "native_upgrade_status.py"
  fi
else
  fail "missing upgrade scripts"
fi

# [6] greenfield detector
echo "[6] native_greenfield_flip.py"
if "$PYTHON" "$PLUGIN_DIR/scripts/native_greenfield_flip.py" --help 2>/dev/null; then
  : # no --help
fi
if [ -f "$PLUGIN_DIR/scripts/native_greenfield_flip.py" ]; then
  ok "greenfield helper present"
else
  fail "native_greenfield_flip.py missing"
fi

if [ "$QUICK" = true ]; then
  echo ""
  echo "  Quick mode — skipping smoke + activation"
else
  echo "[7] verify_activation.sh"
  if bash "$PLUGIN_DIR/scripts/verify_activation.sh" >/dev/null 2>&1; then
    ok "activation 11/11"
  else
    fail "verify_activation"
  fi

  echo "[8] smoke_test.sh"
  if bash "$PLUGIN_DIR/scripts/smoke_test.sh" >/dev/null 2>&1; then
    ok "smoke 15/15"
  else
    fail "smoke_test"
  fi

  echo "[9] runtime preflight"
  if "$PYTHON" "$PLUGIN_DIR/scripts/ensure_runtime_preflight.py" >/dev/null 2>&1; then
    ok "ensure_runtime_preflight"
  else
    fail "preflight"
  fi

  echo "[10] MCP reload stamp (non-fatal)"
  if "$PYTHON" -c "
import sys
sys.path.insert(0, '$PLUGIN_DIR')
from mcp_server.mcp_reload import request_mcp_reload, read_reload_request
request_mcp_reload(reason='bug_hunt_test')
assert read_reload_request() is not None
" 2>/dev/null; then
    ok "mcp_reload request round-trip"
  else
    fail "mcp_reload"
  fi
fi

echo ""
echo "  Passed: $PASS  Failed: $FAIL"
echo ""
if [ "$FAIL" -eq 0 ]; then
  echo "  ✅ Bug hunt matrix clean."
  exit 0
fi
echo "  ❌ $FAIL scenario(s) failed."
exit 1
