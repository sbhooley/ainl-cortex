#!/usr/bin/env bash
# Claude Code may copy the plugin without the venv's `python` shim; support fallbacks.
set -euo pipefail
ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")" && pwd)}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
cd "$ROOT"

for py in .venv/bin/python .venv/bin/python3 .venv/bin/python3.14 .venv/bin/python3.13 .venv/bin/python3.12 .venv/bin/python3.11; do
  if [[ -x "$py" ]]; then
    exec "$py" -m mcp_server.server
  fi
done

# venv copy sometimes contains site-packages but no python binary
if [[ -d .venv/lib ]]; then
  for d in .venv/lib/python*; do
    if [[ -d "$d/site-packages" ]]; then
      export PYTHONPATH="${ROOT}:${d}/site-packages${PYTHONPATH:+:${PYTHONPATH}}"
    fi
  done
fi

if command -v python3 >/dev/null 2>&1; then
  exec python3 -m mcp_server.server
fi

echo "ainl-graph-memory: no Python in .venv/bin and no python3 on PATH" >&2
exit 1
