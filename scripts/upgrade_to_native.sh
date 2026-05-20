#!/usr/bin/env bash
# Delegates to cross-platform scripts/upgrade_to_native.py
set -euo pipefail
PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PLUGIN_DIR"
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1; then
    exec "$py" "$PLUGIN_DIR/scripts/upgrade_to_native.py" "$@"
  fi
done
echo "ERROR: python3 not found" >&2
exit 1
