#!/usr/bin/env bash
# Claude Code may copy the plugin without the venv's `python` shim; support fallbacks.
set -euo pipefail
ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")" && pwd)}"
# Include mcp_server/ so legacy `from node_types import …` in tool bodies resolves
# the same way as hooks (see commit 19dd4b5 / package-mode MCP launch).
export PYTHONPATH="${ROOT}/mcp_server:${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
cd "$ROOT"

_preflight_import_compat() {
  local py="$1"
  "$py" "$ROOT/scripts/ensure_mcp_import_compat.py" 2>/dev/null || true
}

for py in .venv/bin/python .venv/bin/python3 .venv/bin/python3.14 .venv/bin/python3.13 .venv/bin/python3.12 .venv/bin/python3.11; do
  if [[ -x "$py" ]]; then
    _preflight_import_compat "$py"
    exec "$py" -m mcp_server.server
  fi
done

# venv copy sometimes contains site-packages but no python binary
if [[ -d .venv/lib ]]; then
  for d in .venv/lib/python*; do
    if [[ -d "$d/site-packages" ]]; then
      export PYTHONPATH="${ROOT}/mcp_server:${ROOT}:${d}/site-packages${PYTHONPATH:+:${PYTHONPATH}}"
    fi
  done
fi

if command -v python3 >/dev/null 2>&1; then
  _preflight_import_compat python3
  exec python3 -m mcp_server.server
fi

echo "ainl-cortex: no Python in .venv/bin and no python3 on PATH" >&2
exit 1
