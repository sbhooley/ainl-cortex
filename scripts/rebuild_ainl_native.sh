#!/usr/bin/env bash
# Rebuild ainl_native into the plugin .venv (required after git pull when store_backend=native).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Run setup.sh first (missing .venv)" >&2
  exit 1
fi

"$ROOT/.venv/bin/pip" install -q 'maturin>=1.0,<2.0'
export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
"$ROOT/.venv/bin/maturin" develop --release --manifest-path "$ROOT/ainl_native/Cargo.toml"

"$ROOT/.venv/bin/python" -c "import ainl_native; print('ainl_native OK:', ainl_native.__file__)"
