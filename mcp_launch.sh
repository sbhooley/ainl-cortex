#!/usr/bin/env bash
# Cross-platform MCP launch (delegates to mcp_launch.py for venv Scripts vs bin).
set -euo pipefail
ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")" && pwd)}"
cd "$ROOT"
export CLAUDE_PLUGIN_ROOT="$ROOT"

for py in python3 python py; do
  if command -v "$py" >/dev/null 2>&1; then
    exec "$py" "$ROOT/mcp_launch.py"
  fi
done

echo "ainl-cortex: python not found on PATH — run setup.sh or setup.ps1" >&2
exit 1
