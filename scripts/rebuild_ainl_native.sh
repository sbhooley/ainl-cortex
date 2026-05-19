#!/usr/bin/env bash
# Refresh ainl_native in the plugin .venv (PyPI upgrade or source rebuild).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Run setup.sh first (missing .venv)" >&2
  exit 1
fi

# Prefer source when plugin Rust tree is being developed
if [[ -d "$ROOT/ainl_native/src" ]] && command -v rustc >/dev/null 2>&1; then
  bash "$ROOT/scripts/install_ainl_native.sh" --prefer-source
else
  bash "$ROOT/scripts/install_ainl_native.sh"
fi

"$ROOT/.venv/bin/python" -c "import ainl_native; print('ainl_native OK:', ainl_native.__file__)"
