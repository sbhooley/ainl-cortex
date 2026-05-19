#!/usr/bin/env bash
# claude_do_native_upgrade.sh — Single entrypoint for Claude Code when the user asks to
# install Rust, upgrade to the native backend, or migrate graph memory.
#
# Usage (from plugin root, or any cwd):
#   bash scripts/claude_do_native_upgrade.sh
#   bash scripts/claude_do_native_upgrade.sh --dry-run
#
# Claude: prefer this over calling migrate_to_native.py or editing config.json.
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$PLUGIN_DIR/.venv/bin/python"
DRY=false

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=true ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

if [[ ! -x "$PY" ]]; then
  echo "ERROR: .venv missing — run: cd $PLUGIN_DIR && bash setup.sh" >&2
  exit 2
fi

echo "=== AINL Cortex — Claude native upgrade ==="
echo ""

EXTRA=()
[ "$DRY" = true ] && EXTRA+=(--dry-run)

# Status first (human-readable banner on stderr, JSON logic inside python)
"$PY" "$PLUGIN_DIR/scripts/native_upgrade_status.py" || true

echo ""
echo "=== Executing recommended actions ==="
if ! "$PY" "$PLUGIN_DIR/scripts/native_upgrade_status.py" --execute "${EXTRA[@]}"; then
  echo "" >&2
  echo "Upgrade failed. Diagnose with:" >&2
  echo "  cd $PLUGIN_DIR && bash scripts/bug_hunt_matrix.sh" >&2
  exit 1
fi

echo ""
echo "=== Done ==="
echo "Tell the user to run **/reload-plugins** in Claude Code, then verify with **/mcp**."
