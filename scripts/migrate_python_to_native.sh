#!/usr/bin/env bash
# Five-phase Python -> Rust migration wrapper. Bails on any non-zero exit.
#
# Phase 1: Sanity check that ainl_native is built.
# Phase 2: Dry-run migration (catches schema drift before any writes).
# Phase 3: Real migration (atomic per-project; --strict by default).
# Phase 4: Verification (row counts + sample round-trip).
# Phase 5: Inject verify=passed into the latest report, then flip config.
#
# On any failure, prints what to do next (typically: read the JSON report
# under logs/, then run `migrate_to_python.py --purge-native` to roll back).

set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PLUGIN_ROOT"

if [ ! -x ".venv/bin/python" ]; then
    echo "ERROR: .venv/bin/python not found. Run setup.sh first." >&2
    exit 2
fi
PY=".venv/bin/python"

echo "==> Phase 1: ainl_native availability check"
if ! "$PY" -c "import ainl_native" 2>/dev/null; then
    echo "ERROR: ainl_native module not built." >&2
    echo "       Run: cd ainl_native && ../.venv/bin/maturin develop --release" >&2
    exit 1
fi
echo "  ainl_native is importable."

echo
echo "==> Phase 2: dry-run migration"
"$PY" migrate_to_native.py --dry-run --strict

echo
echo "==> Phase 3: real migration (atomic, --strict)"
"$PY" migrate_to_native.py --strict

echo
echo "==> Phase 4: verification"
if ! "$PY" scripts/verify_migration.py; then
    echo
    echo "ERROR: verification failed. Do NOT flip config. Inspect:"
    echo "    logs/migration_latest.json"
    echo "    logs/verify_latest.json"
    echo "Roll back with: $PY migrate_to_python.py --purge-native"
    exit 1
fi

echo
echo "==> Phase 5: inject verify=passed and flip config"
"$PY" migrate_to_native.py --inject-verify-status passed
"$PY" migrate_to_native.py --flip-config

echo
echo "Migration complete. Restart Claude Code for the new backend to take effect."
