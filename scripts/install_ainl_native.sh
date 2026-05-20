#!/usr/bin/env bash
# Install ainl_native into the plugin .venv: PyPI wheel first, maturin fallback.
#
# Usage (from plugin root):
#   bash scripts/install_ainl_native.sh
#   bash scripts/install_ainl_native.sh --prefer-source   # maturin when Rust is available
#
# Env:
#   AINL_NATIVE_MIN_VERSION   (default 0.1.1)
#   AINL_NATIVE_BUILD_FROM_SOURCE=1  — skip PyPI, use maturin only
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PREFER_SOURCE=false
while [ $# -gt 0 ]; do
  case "$1" in
    --prefer-source) PREFER_SOURCE=true ;;
    -h|--help)
      sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

MIN_VER="${AINL_NATIVE_MIN_VERSION:-0.1.1}"
MANIFEST="$PLUGIN_DIR/ainl_native/Cargo.toml"

PY=$(python3 -c "import sys; from pathlib import Path; sys.path.insert(0,'$PLUGIN_DIR'); from mcp_server.platform_paths import venv_python; print(venv_python(Path('$PLUGIN_DIR')) or '')")
PIP=$(python3 -c "import sys; from pathlib import Path; sys.path.insert(0,'$PLUGIN_DIR'); from mcp_server.platform_paths import venv_pip; print(venv_pip(Path('$PLUGIN_DIR')) or '')")

if [[ -z "$PY" || ! -f "$PY" ]]; then
  echo "error: missing $PLUGIN_DIR/.venv — run setup.sh or setup.ps1 first" >&2
  exit 1
fi

_rust_available() {
  command -v rustc >/dev/null 2>&1 && command -v cargo >/dev/null 2>&1
}

_verify_import() {
  "$PY" -c "import ainl_native; print(ainl_native.__file__)"
}

_pip_install() {
  echo "  Installing ainl_native>=${MIN_VER} from PyPI..."
  if "$PIP" install --quiet --upgrade "ainl_native>=${MIN_VER}"; then
    _verify_import >/dev/null
    echo "  [ok] ainl_native from PyPI"
    return 0
  fi
  return 1
}

_maturin_develop() {
  if ! _rust_available; then
    return 1
  fi
  echo "  Building ainl_native from source (maturin)..."
  "$PIP" install --quiet 'maturin>=1.0,<2.0' 2>/dev/null || true
  export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
  if PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
    "$PY" -m maturin develop --release --manifest-path "$MANIFEST" >/dev/null 2>&1; then
    _verify_import >/dev/null
    echo "  [ok] ainl_native built from source"
    return 0
  fi
  return 1
}

if [[ "${AINL_NATIVE_BUILD_FROM_SOURCE:-}" =~ ^(1|true|yes|on)$ ]]; then
  PREFER_SOURCE=true
fi

if [[ "$PREFER_SOURCE" == "true" ]]; then
  if _maturin_develop; then
    exit 0
  fi
  echo "  [warn] source build failed; trying PyPI..." >&2
  _pip_install && exit 0
  echo "  [error] could not install ainl_native" >&2
  exit 1
fi

if _pip_install; then
  exit 0
fi

echo "  [info] PyPI install failed for this platform; trying source build..." >&2
if _maturin_develop; then
  exit 0
fi

echo "  [error] ainl_native not available (no matching PyPI wheel and no Rust build)" >&2
echo "          Supported: macOS, Linux x86_64/aarch64, Windows — or install Rust from https://rustup.rs" >&2
exit 1
