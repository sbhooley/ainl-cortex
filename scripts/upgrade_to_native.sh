#!/usr/bin/env bash
# upgrade_to_native.sh — One-shot native backend upgrade for AINL Cortex.
#
# Orchestrates: Rust (optional) → ainl_native → migrate (if data) → flip config → MCP reload nudge.
#
# Usage:
#   bash scripts/upgrade_to_native.sh              # interactive when memory exists
#   bash scripts/upgrade_to_native.sh --yes        # non-interactive (CI / Claude agent)
#   bash scripts/upgrade_to_native.sh --auto-install-rust
#   bash scripts/upgrade_to_native.sh --skip-migrate   # ainl_native only + flip if already migrated
#
# Claude Code (user asked to upgrade): prefer scripts/claude_do_native_upgrade.sh
#
# Called from setup.sh when policy allows, or ask Claude:
#   "Run bash scripts/upgrade_to_native.sh in the ainl-cortex plugin directory."
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$PLUGIN_DIR/.venv/bin/python"
AUTO_RUST=false
ASSUME_YES=false
SKIP_MIGRATE=false

while [ $# -gt 0 ]; do
  case "$1" in
    --auto-install-rust) AUTO_RUST=true ;;
    --yes|-y) ASSUME_YES=true ;;
    --skip-migrate) SKIP_MIGRATE=true ;;
    -h|--help)
      sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

if [[ ! -x "$PY" ]]; then
  echo "ERROR: run setup.sh first (.venv missing)." >&2
  exit 2
fi

echo ""
echo "=== AINL Cortex — Upgrade to native backend ==="
echo ""

# ── Current backend ─────────────────────────────────────────────────────────
CURRENT_BACKEND=$("$PY" -c "import json; print(json.load(open('$PLUGIN_DIR/config.json'))['memory'].get('store_backend','python'))")
if [ "$CURRENT_BACKEND" = "native" ]; then
  echo "  [ok] store_backend is already native."
  "$PY" -c "
import sys
sys.path.insert(0, '$PLUGIN_DIR')
from mcp_server.mcp_reload import request_mcp_reload
request_mcp_reload(reason='already_native')
"
  echo "  Run /reload-plugins in Claude Code if MCP was started before this check."
  exit 0
fi

# ── Step 1: Rust (optional — PyPI wheel often enough) ───────────────────────
if ! command -v rustc >/dev/null 2>&1; then
  if [ "$AUTO_RUST" = true ] && command -v curl >/dev/null 2>&1; then
    echo "  Installing Rust via rustup (--auto-install-rust)..."
    if curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
        | sh -s -- -y --no-modify-path 2>&1 | grep -E "^(info|warning|error|  Rust)" || true; then
      # shellcheck disable=SC1091
      source "$HOME/.cargo/env" 2>/dev/null || true
    fi
  fi
  if command -v rustc >/dev/null 2>&1; then
    echo "  [ok] Rust $(rustc --version | cut -d' ' -f2)"
  else
    echo "  [info] Rust not installed — continuing (PyPI ainl_native wheel may still work)"
  fi
else
  echo "  [ok] Rust $(rustc --version | cut -d' ' -f2)"
fi

# ── Step 2: ainl_native ─────────────────────────────────────────────────────
echo "  Installing ainl_native..."
if ! bash "$PLUGIN_DIR/scripts/install_ainl_native.sh"; then
  echo "ERROR: ainl_native install failed. Python backend unchanged." >&2
  exit 1
fi
if ! "$PY" -c "import ainl_native" 2>/dev/null; then
  echo "ERROR: ainl_native not importable after install." >&2
  exit 1
fi
echo "  [ok] ainl_native importable"

# ── Step 3: Confirm if graph memory exists ─────────────────────────────────
HAS_DATA=$("$PY" -c "
from pathlib import Path
import sqlite3
home = Path.home()
for db in home.glob('.claude/projects/*/graph_memory/ainl_memory.db'):
    if db.stat().st_size < 8192:
        continue
    try:
        conn = sqlite3.connect(str(db))
        try:
            n = conn.execute('SELECT COUNT(*) FROM ainl_graph_nodes').fetchone()[0]
            if n > 0:
                print('yes')
                raise SystemExit(0)
        except sqlite3.Error:
            if db.stat().st_size >= 8192:
                print('yes')
                raise SystemExit(0)
        finally:
            conn.close()
    except OSError:
        pass
print('no')
")

if [ "$HAS_DATA" = "yes" ] && [ "$SKIP_MIGRATE" = false ]; then
  if [ "$ASSUME_YES" = false ] && [ -t 0 ]; then
    echo ""
    echo "  Existing graph memory was found under ~/.claude/projects/*/graph_memory/."
    echo "  Migration will copy data to ainl_native.db (dry-run → migrate → verify → flip)."
    printf "  Proceed? [y/N] "
    CONFIRM=""
    if read -rt 60 CONFIRM; then : ; else CONFIRM=""; fi
    case "$CONFIRM" in
      y|Y|yes|YES) ;;
      *) echo "  Aborted — Python backend unchanged."; exit 0 ;;
    esac
  elif [ "$ASSUME_YES" = false ]; then
    echo "ERROR: memory data exists; re-run with --yes (non-interactive) or use a TTY." >&2
    exit 2
  fi
fi

# ── Step 4: Migrate or greenfield flip ──────────────────────────────────────
if [ "$SKIP_MIGRATE" = true ]; then
  echo "  [--skip-migrate] Skipping migration script."
elif [ "$HAS_DATA" = "yes" ]; then
  echo "  Running 5-phase migration..."
  bash "$PLUGIN_DIR/scripts/migrate_python_to_native.sh"
else
  echo "  No graph memory data — greenfield native flip."
  "$PY" "$PLUGIN_DIR/scripts/native_greenfield_flip.py"
fi

FINAL_BACKEND=$("$PY" -c "import json; print(json.load(open('$PLUGIN_DIR/config.json'))['memory'].get('store_backend','python'))")
if [ "$FINAL_BACKEND" != "native" ]; then
  echo "ERROR: store_backend is still '$FINAL_BACKEND' after upgrade." >&2
  exit 1
fi
echo "  [ok] store_backend = native"

# ── Step 5: MCP reload nudge ─────────────────────────────────────────────────
"$PY" -c "
import sys
sys.path.insert(0, '$PLUGIN_DIR')
from mcp_server.mcp_reload import request_mcp_reload
request_mcp_reload(reason='upgrade_to_native')
"

echo ""
echo "=== Native upgrade complete ==="
echo "  • config.json: store_backend = native"
echo "  • Next: run /reload-plugins in Claude Code (or fully restart)"
echo ""
