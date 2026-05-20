#!/usr/bin/env bash
# Bootstrap Python + .venv when no python3 on PATH (macOS/Linux MCP entry).
set -euo pipefail
PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PY="$PLUGIN_DIR/.venv/bin/python3"
if [[ -x "$VENV_PY" ]] || [[ -x "$PLUGIN_DIR/.venv/bin/python" ]]; then
  exit 0
fi

echo "ainl-cortex: no Python on PATH — bootstrapping via uv..." >&2
UV_VER="0.6.14"
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
case "$OS" in
  darwin)
    ASSET="uv-${ARCH}-apple-darwin.tar.gz"
    [[ "$ARCH" == "x86_64" ]] || ASSET="uv-aarch64-apple-darwin.tar.gz"
    ;;
  linux)
    case "$ARCH" in
      aarch64|arm64) ASSET="uv-aarch64-unknown-linux-gnu.tar.gz" ;;
      armv7l|armv6l) ASSET="uv-armv7-unknown-linux-gnueabihf.tar.gz" ;;
      *) ASSET="uv-x86_64-unknown-linux-gnu.tar.gz" ;;
    esac
    ;;
  *) echo "unsupported OS: $OS" >&2; exit 1 ;;
esac

BOOT="$PLUGIN_DIR/.ainl-bootstrap/uv"
mkdir -p "$BOOT"
URL="https://github.com/astral-sh/uv/releases/download/${UV_VER}/${ASSET}"
ARCHIVE="$BOOT/$ASSET"
UV="$BOOT/uv"

if [[ ! -x "$UV" ]]; then
  curl -fsSL -o "$ARCHIVE" "$URL"
  tar -xzf "$ARCHIVE" -C "$BOOT"
  chmod +x "$UV" 2>/dev/null || true
fi

export UV_PYTHON_INSTALL_DIR="$PLUGIN_DIR/.ainl-bootstrap/pythons"
mkdir -p "$UV_PYTHON_INSTALL_DIR"
"$UV" python install 3.12
"$UV" venv "$PLUGIN_DIR/.venv" --python 3.12 --seed
