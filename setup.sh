#!/usr/bin/env bash
# setup.sh — Install and activate ainl-cortex for Claude Code.
#
# Usage:
#     bash setup.sh                  # interactive (or python-only when stdin not a tty)
#     bash setup.sh --python-only    # never install Rust, never build native, never migrate
#     bash setup.sh --no-rust        # alias for --python-only
#     bash setup.sh --auto-install-rust   # unattended install of Rust via rustup
#     bash setup.sh --help
#
# Env override (takes precedence over flags):
#     AINL_CORTEX_INSTALL_MODE=python_only   # same as --python-only
#     AINL_CORTEX_INSTALL_MODE=auto_rust     # same as --auto-install-rust
#     AINL_CORTEX_INSTALL_MODE=interactive   # force a prompt even when stdin not a tty
#
# Migration is now a SEPARATE step. setup.sh never flips store_backend to
# "native" automatically. After install, run:
#     bash scripts/migrate_python_to_native.sh
#
# Safe to re-run — every step is idempotent.
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
SETTINGS="$HOME/.claude/settings.json"
MARKETPLACE="$HOME/.claude/ainl-local-marketplace"

# ── Argument parsing ───────────────────────────────────────────────────────
INSTALL_MODE=""   # one of: python_only, auto_rust, interactive (or empty)
SHOW_HELP=false

while [ $# -gt 0 ]; do
    case "$1" in
        --python-only|--no-rust)
            INSTALL_MODE="python_only"
            ;;
        --auto-install-rust)
            INSTALL_MODE="auto_rust"
            ;;
        --interactive)
            INSTALL_MODE="interactive"
            ;;
        --help|-h)
            SHOW_HELP=true
            ;;
        *)
            echo "WARNING: unknown argument: $1 (ignored)" >&2
            ;;
    esac
    shift
done

if [ "$SHOW_HELP" = "true" ]; then
    head -n 18 "$0" | sed 's/^# \{0,1\}//'
    exit 0
fi

# Env override beats flags so CI / agents can pin behavior.
if [ -n "${AINL_CORTEX_INSTALL_MODE:-}" ]; then
    case "${AINL_CORTEX_INSTALL_MODE}" in
        python_only|auto_rust|interactive)
            INSTALL_MODE="${AINL_CORTEX_INSTALL_MODE}"
            ;;
        *)
            echo "WARNING: AINL_CORTEX_INSTALL_MODE='${AINL_CORTEX_INSTALL_MODE}' invalid; ignoring." >&2
            ;;
    esac
fi

# Default policy when nothing is set:
#   - tty: interactive (prompt user)
#   - non-tty (CI / agent): python_only (no surprise rustup)
if [ -z "$INSTALL_MODE" ]; then
    if [ -t 0 ]; then
        INSTALL_MODE="interactive"
    else
        INSTALL_MODE="python_only"
    fi
fi

echo ""
echo "=== AINL Cortex — Setup ==="
echo ""
echo "  Install mode: $INSTALL_MODE"
echo "  What this script does:"
echo "    1. Verifies Python 3.10+"
echo "    2. (Optionally) installs Rust toolchain — see install mode above"
echo "    3. Creates a Python venv and installs dependencies"
echo "    4. (Optionally) builds the ainl_native Rust extension"
echo "    5. Registers the plugin with Claude Code"
echo "    6. Runs verification tests"
echo ""
echo "  NOTE: setup.sh never flips store_backend or migrates data."
echo "        After install, run: bash scripts/migrate_python_to_native.sh"
echo ""

# ── 1. Python check ────────────────────────────────────────────────────────
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found. Install Python 3.10+ from https://python.org and retry." >&2
    exit 1
fi
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 10 ]]; }; then
    echo "ERROR: Python $PY_VER found but 3.10+ is required." >&2
    exit 1
fi
echo "  [ok] Python $PY_VER"

# ── 2. Rust check + opt-in install ─────────────────────────────────────────
RUST_AVAILABLE=false
if command -v rustc >/dev/null 2>&1; then
    RUST_AVAILABLE=true
    RUST_VER=$(rustc --version | cut -d' ' -f2)
    echo "  [ok] Rust $RUST_VER (native backend can be enabled later)"
else
    case "$INSTALL_MODE" in
        python_only)
            echo "  [info] python_only mode — skipping Rust install"
            ;;
        auto_rust)
            if command -v curl >/dev/null 2>&1; then
                echo "  Rust not found — installing via rustup (--auto-install-rust)..."
                if curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
                    | sh -s -- -y --no-modify-path 2>&1 | grep -E "^(info|warning|error|  Rust)" || true; then
                    source "$HOME/.cargo/env" 2>/dev/null || true
                    if command -v rustc >/dev/null 2>&1; then
                        RUST_AVAILABLE=true
                        echo "  [ok] Rust $(rustc --version | cut -d' ' -f2) installed"
                    fi
                fi
                if [ "$RUST_AVAILABLE" = "false" ]; then
                    echo "  [warn] Rust install failed — continuing with Python backend"
                fi
            else
                echo "  [warn] curl unavailable — cannot auto-install Rust; continuing with Python backend"
            fi
            ;;
        interactive)
            if [ -t 0 ]; then
                echo ""
                echo "  Rust is not installed. The native backend offers richer session"
                echo "  memory and faster recall. Install now?"
                echo "    [1] Install Rust via rustup (https://rustup.rs)"
                echo "    [2] Skip — use the Python backend (you can install later)"
                echo ""
                # Reads ONE keypress. Accept default = 2 on EOF / blank.
                printf "  Choice [1/2] (default 2): "
                CHOICE=""
                if read -rt 30 CHOICE; then : ; else CHOICE="2"; fi
                if [ "$CHOICE" = "1" ]; then
                    if command -v curl >/dev/null 2>&1; then
                        if curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
                            | sh -s -- -y --no-modify-path 2>&1 | grep -E "^(info|warning|error|  Rust)" || true; then
                            source "$HOME/.cargo/env" 2>/dev/null || true
                            if command -v rustc >/dev/null 2>&1; then
                                RUST_AVAILABLE=true
                                echo "  [ok] Rust $(rustc --version | cut -d' ' -f2) installed"
                            fi
                        fi
                        if [ "$RUST_AVAILABLE" = "false" ]; then
                            echo "  [warn] Rust install failed — continuing with Python backend"
                        fi
                    else
                        echo "  [warn] curl unavailable — cannot install Rust; continuing with Python backend"
                    fi
                else
                    echo "  Skipping Rust install. Run again with --auto-install-rust to install later."
                fi
            else
                # Belt-and-suspenders: even if INSTALL_MODE=interactive was forced
                # but stdin is not a tty, fall back to python-only (no surprise).
                echo "  [info] interactive mode requested but stdin is not a tty — skipping Rust install"
            fi
            ;;
    esac
fi

# ── 3. Create venv + install dependencies ──────────────────────────────────
echo "  Creating Python venv..."
python3 -m venv "$PLUGIN_DIR/.venv"
"$PLUGIN_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$PLUGIN_DIR/.venv/bin/pip" install --quiet -r "$PLUGIN_DIR/requirements-ainl.txt"
echo "  [ok] Dependencies installed"

# ── 4. Configure config.json (always python by default) ────────────────────
echo "  Configuring plugin..."
python3 - "$PLUGIN_DIR" <<'PYEOF'
import json, pathlib, sys, uuid

plugin_dir = pathlib.Path(sys.argv[1])
config_path = plugin_dir / "config.json"

with open(config_path) as f:
    cfg = json.load(f)

# Always default to Python; user opts into native via the migration script.
cfg.setdefault("memory", {})
if cfg["memory"].get("store_backend") not in ("python", "native"):
    cfg["memory"]["store_backend"] = "python"

# Default to per-repo project isolation (issue 1) for fresh installs that
# don't have the field set; existing installs keep their setting.
cfg["memory"].setdefault("project_isolation_mode", "per_repo")

cfg.setdefault("a2a", {})["enabled"] = False
cfg["a2a"].pop("bridge_script", None)

cfg.setdefault("install_id", str(uuid.uuid4()))
cfg.setdefault("telemetry", {}).setdefault("remote", {}).setdefault("enabled", True)

with open(config_path, "w") as f:
    json.dump(cfg, f, indent=2)
print(f"    config.json: store_backend={cfg['memory']['store_backend']!r} "
      f"project_isolation_mode={cfg['memory'].get('project_isolation_mode')!r}")
PYEOF
echo "  [ok] Config updated"

# Read current backend (untouched by setup.sh — the user set it).
CURRENT_BACKEND=$(python3 -c "import json; print(json.load(open('$PLUGIN_DIR/config.json'))['memory']['store_backend'])")

# ── 5. Build native extension (only if Rust is available) ──────────────────
NATIVE_BUILT=false
if [ "$RUST_AVAILABLE" = "true" ]; then
    echo "  Building ainl_native Rust extension..."
    "$PLUGIN_DIR/.venv/bin/pip" install maturin --quiet 2>/dev/null || true
    if PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
        "$PLUGIN_DIR/.venv/bin/maturin" develop --release \
        --manifest-path "$PLUGIN_DIR/ainl_native/Cargo.toml" 2>&1 | tail -3; then
        NATIVE_BUILT=true
        echo "  [ok] ainl_native built"
    else
        echo "  [warn] ainl_native build failed — Python backend will be used"
    fi
else
    echo "  [info] Skipping ainl_native build (Rust not installed)"
fi

# ── 6. Migration deferral notice ───────────────────────────────────────────
if [ "$NATIVE_BUILT" = "true" ] && [ "$CURRENT_BACKEND" = "python" ]; then
    HAS_DATA=$(python3 -c "
import pathlib
dbs = list(pathlib.Path.home().glob('.claude/projects/*/graph_memory/ainl_memory.db'))
print('yes' if dbs else 'no')
")
    echo ""
    echo "  Native extension is built but the plugin is currently configured"
    echo "  to use the Python backend (safe default)."
    if [ "$HAS_DATA" = "yes" ]; then
        echo "  You have existing memory data. To migrate to native, run:"
        echo "      bash scripts/migrate_python_to_native.sh"
        echo "  This runs dry-run -> migrate -> verify -> flip in 5 phases,"
        echo "  with rollback available via migrate_to_python.py."
    else
        echo "  No existing memory data found. To switch to native, run:"
        echo "      bash scripts/migrate_python_to_native.sh"
    fi
    echo ""
fi

# ── 7. Set up local marketplace ────────────────────────────────────────────
echo "  Setting up plugin marketplace..."
mkdir -p "$MARKETPLACE/.claude-plugin"
mkdir -p "$MARKETPLACE/plugins"

LINK_PATH="$MARKETPLACE/plugins/ainl-cortex"
if [[ -L "$LINK_PATH" ]] || [[ -e "$LINK_PATH" ]]; then
    rm -f "$LINK_PATH"
fi
ln -s "$PLUGIN_DIR" "$LINK_PATH"

cat > "$MARKETPLACE/.claude-plugin/marketplace.json" <<JSONEOF
{
  "name": "ainl-local",
  "version": "1.0.0",
  "description": "Local marketplace: AINL Cortex",
  "owner": { "name": "local" },
  "plugins": [
    {
      "name": "ainl-cortex",
      "description": "Graph-native memory, self-learning, and multi-agent coordination for Claude Code",
      "source": "./plugins/ainl-cortex"
    }
  ]
}
JSONEOF
echo "  [ok] Marketplace configured"

# ── 8. Register plugin in ~/.claude/settings.json ──────────────────────────
echo "  Registering plugin with Claude Code..."
python3 - "$SETTINGS" "$MARKETPLACE" <<'PYEOF'
import json, pathlib, sys

settings_path = pathlib.Path(sys.argv[1])
marketplace = sys.argv[2]

settings = {}
if settings_path.exists():
    try:
        with open(settings_path) as f:
            settings = json.load(f)
    except (json.JSONDecodeError, OSError):
        print(f"    WARNING: could not parse {settings_path}, creating fresh")

settings.setdefault("extraKnownMarketplaces", {})["ainl-local"] = {
    "source": {"source": "directory", "path": marketplace}
}
settings.setdefault("enabledPlugins", {})["ainl-cortex@ainl-local"] = True

settings_path.parent.mkdir(parents=True, exist_ok=True)
with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
print(f"    {settings_path} updated")
PYEOF
echo "  [ok] Plugin registered"

# ── 9. Self-verification ───────────────────────────────────────────────────
echo "  Running self-verification..."
echo ""
bash "$PLUGIN_DIR/scripts/verify_activation.sh" || true
bash "$PLUGIN_DIR/scripts/smoke_test.sh" || true

# ── 10. Telemetry: install event ───────────────────────────────────────────
"$PLUGIN_DIR/.venv/bin/python" - "$PLUGIN_DIR" <<'PYEOF' &
import sys
from pathlib import Path
plugin_dir = Path(sys.argv[1])
sys.path.insert(0, str(plugin_dir / "hooks"))
try:
    from telemetry import capture
    capture("install", {"backend": __import__("json").loads((plugin_dir / "config.json").read_text()).get("memory", {}).get("store_backend", "python")}, plugin_dir, blocking=True)
except Exception:
    pass
PYEOF

# ── Done ───────────────────────────────────────────────────────────────────
echo "=== Setup complete! ==="
echo ""
echo "  Plugin dir : $PLUGIN_DIR"
echo "  Backend    : $CURRENT_BACKEND  (native built: $NATIVE_BUILT)"
echo "  Venv       : $PLUGIN_DIR/.venv"
echo ""
if [ "$NATIVE_BUILT" = "true" ] && [ "$CURRENT_BACKEND" = "python" ]; then
    echo "  To switch to native: bash scripts/migrate_python_to_native.sh"
    echo ""
fi
echo "Next step: restart Claude Code."
echo ""
echo "You should see:"
echo "  • [AINL Cortex] banner at session start"
echo "  • ~30 new MCP tools under /mcp (memory + goals + ainl + a2a)"
echo ""
