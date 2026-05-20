#!/usr/bin/env bash
# setup.sh — Install and activate ainl-cortex for Claude Code.
#
# Usage:
#     bash setup.sh                  # interactive (or python-only when stdin not a tty)
#     bash setup.sh --python-only    # never install Rust, never build native, never migrate
#     bash setup.sh --no-rust        # alias for --python-only
#     bash setup.sh --auto-install-rust   # unattended install of Rust via rustup
#     bash setup.sh --enable-native       # upgrade to native after install (see policy below)
#     bash setup.sh --enable-native --yes # non-interactive native upgrade (incl. migrate)
#     bash setup.sh --restore-from ~/.claude/backups/ainl-cortex-<timestamp>
#     bash setup.sh --help
#
# Env override (takes precedence over flags):
#     AINL_CORTEX_INSTALL_MODE=python_only   # same as --python-only
#     AINL_CORTEX_INSTALL_MODE=auto_rust     # same as --auto-install-rust
#     AINL_CORTEX_INSTALL_MODE=interactive   # force a prompt even when stdin not a tty
#     AINL_CORTEX_ENABLE_NATIVE=1            # same as --enable-native
#
# Native upgrade policy (default install stays Python):
#   • Non-tty (CI/agents): Python only unless --enable-native --yes
#   • Fresh install, ainl_native ready, no graph data: auto native (greenfield)
#   • Existing memory + tty: prompt to run scripts/upgrade_to_native.sh
#   • --enable-native: run scripts/upgrade_to_native.sh after install
#
# Manual upgrade anytime:
#     bash scripts/upgrade_to_native.sh
#
# Safe to re-run — every step is idempotent.
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
SETTINGS="$HOME/.claude/settings.json"
MARKETPLACE="$HOME/.claude/ainl-local-marketplace"

# Do not register disposable /tmp verification clones as the user's marketplace plugin.
case "$PLUGIN_DIR" in
  /tmp/*|/private/tmp/*)
    echo "ERROR: setup.sh was run from a temp directory:" >&2
    echo "  $PLUGIN_DIR" >&2
    echo "  That would repoint $MARKETPLACE/plugins/ainl-cortex at a throwaway clone." >&2
    echo "  Run instead: cd ~/.claude/plugins/ainl-cortex && bash setup.sh" >&2
    exit 1
    ;;
esac

# ── Argument parsing ───────────────────────────────────────────────────────
INSTALL_MODE=""   # one of: python_only, auto_rust, interactive (or empty)
SHOW_HELP=false
RESTORE_FROM=""
ENABLE_NATIVE=false
ASSUME_YES=false

while [ $# -gt 0 ]; do
    case "$1" in
        --python-only|--no-rust)
            INSTALL_MODE="python_only"
            ;;
        --auto-install-rust)
            INSTALL_MODE="auto_rust"
            ;;
        --enable-native)
            ENABLE_NATIVE=true
            ;;
        --yes|-y)
            ASSUME_YES=true
            ;;
        --interactive)
            INSTALL_MODE="interactive"
            ;;
        --restore-from)
            shift
            RESTORE_FROM="${1:-}"
            if [ -z "$RESTORE_FROM" ]; then
                echo "ERROR: --restore-from requires a backup directory path" >&2
                exit 1
            fi
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
    head -n 28 "$0" | sed 's/^# \{0,1\}//'
    exit 0
fi

if [ "${AINL_CORTEX_ENABLE_NATIVE:-}" = "1" ] || [ "${AINL_CORTEX_ENABLE_NATIVE:-}" = "true" ]; then
    ENABLE_NATIVE=true
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
echo "    4. Installs ainl_native (PyPI wheel; maturin only if wheel unavailable)"
echo "    5. Registers the plugin with Claude Code"
echo "    6. Runs verification tests"
echo "    7. (Optional) upgrades to native backend — see policy in script header"
echo ""
echo "  Default: Python backend (works without Rust). Native upgrade:"
echo "        bash scripts/upgrade_to_native.sh"
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

# ── 3–5. Cross-platform venv, config, hooks, ainl_native (Python) ───────────
SETUP_PY_ARGS=(--plugin-dir "$PLUGIN_DIR" --register-claude)
if [ "$INSTALL_MODE" = "python_only" ]; then
    SETUP_PY_ARGS+=(--python-only)
fi
python3 "$PLUGIN_DIR/scripts/setup_install.py" "${SETUP_PY_ARGS[@]}"

# Read current backend (untouched by setup — user may flip via migration scripts).
CURRENT_BACKEND=$(python3 -c "import json; print(json.load(open('$PLUGIN_DIR/config.json'))['memory']['store_backend'])")

NATIVE_READY=false
_VPY=$(python3 -c "import sys; sys.path.insert(0,'$PLUGIN_DIR'); from mcp_server.platform_paths import venv_python; from pathlib import Path; p=venv_python(Path('$PLUGIN_DIR')); print(p or '')")
if [ -n "$_VPY" ] && "$_VPY" -c "import ainl_native" 2>/dev/null; then
    NATIVE_READY=true
fi
if [ "$NATIVE_READY" = "false" ] && bash "$PLUGIN_DIR/scripts/install_ainl_native.sh"; then
    NATIVE_READY=true
fi

# ── 6. Native upgrade policy ───────────────────────────────────────────────
UPGRADE_RAN=false
HAS_DATA=$(python3 -c "
import pathlib, sqlite3
home = pathlib.Path.home()
for db in home.glob('.claude/projects/*/graph_memory/ainl_memory.db'):
    if db.stat().st_size < 8192:
        continue
    try:
        conn = sqlite3.connect(str(db))
        try:
            n = conn.execute('SELECT COUNT(*) FROM ainl_graph_nodes').fetchone()[0]
            if n > 0:
                print('yes'); raise SystemExit
        except sqlite3.Error:
            if db.stat().st_size >= 8192:
                print('yes'); raise SystemExit
        finally:
            conn.close()
    except OSError:
        pass
print('no')
")

_run_native_upgrade() {
    local extra=()
    [ "$ASSUME_YES" = true ] && extra+=(--yes)
    [ "$INSTALL_MODE" = "auto_rust" ] && extra+=(--auto-install-rust)
    bash "$PLUGIN_DIR/scripts/upgrade_to_native.sh" "${extra[@]}"
}

if [ "$INSTALL_MODE" = "python_only" ]; then
  ENABLE_NATIVE=false
fi

if [ "$NATIVE_READY" = "true" ] && [ "$CURRENT_BACKEND" = "python" ]; then
    if [ "$ENABLE_NATIVE" = true ]; then
        echo "  Running native upgrade (--enable-native)..."
        if _run_native_upgrade; then
            UPGRADE_RAN=true
            CURRENT_BACKEND=native
            echo "  [ok] Native backend enabled"
        else
            echo "  [warn] Native upgrade failed — staying on Python backend"
        fi
    elif [ "$HAS_DATA" = "no" ] && [ -t 0 ] && [ "$INSTALL_MODE" != "python_only" ]; then
        echo "  No graph memory yet — enabling native backend (greenfield)..."
        _saved_assume="$ASSUME_YES"
        ASSUME_YES=true
        if _run_native_upgrade; then
            UPGRADE_RAN=true
            CURRENT_BACKEND=native
            echo "  [ok] Native backend enabled (greenfield)"
        fi
        ASSUME_YES="$_saved_assume"
    elif [ "$HAS_DATA" = "yes" ] && [ -t 0 ] && [ "$INSTALL_MODE" = "interactive" ]; then
        echo ""
        echo "  ainl_native is ready. Existing graph memory was found."
        echo "  Upgrade to the native Rust backend now? (dry-run → migrate → verify)"
        echo "    [1] Yes — run scripts/upgrade_to_native.sh"
        echo "    [2] No  — stay on Python (upgrade later via the same script)"
        printf "  Choice [1/2] (default 2): "
        UP_CHOICE=""
        if read -rt 45 UP_CHOICE; then : ; else UP_CHOICE="2"; fi
        if [ "$UP_CHOICE" = "1" ]; then
            if _run_native_upgrade; then
                UPGRADE_RAN=true
                CURRENT_BACKEND=native
            fi
        else
            echo "  Staying on Python. Upgrade anytime:"
            echo "      bash scripts/upgrade_to_native.sh"
        fi
        echo ""
    elif [ "$NATIVE_READY" = "true" ]; then
        echo ""
        echo "  ainl_native is installed; store_backend remains python (safe default)."
        if [ "$HAS_DATA" = "yes" ]; then
            echo "  Upgrade when ready: bash scripts/upgrade_to_native.sh"
        else
            echo "  Greenfield native: bash scripts/upgrade_to_native.sh --yes"
        fi
        echo ""
    fi
fi

# ── 7–8. Marketplace + settings (done in setup_install.py --register-claude) ─
echo "  [ok] Claude Code marketplace + settings (via setup_install.py)"

# ── 8b. MCP import compat (preflight; setup_install.py also runs this) ─────
if [ -n "$_VPY" ] && [ -f "$PLUGIN_DIR/scripts/ensure_runtime_preflight.py" ]; then
  "$_VPY" "$PLUGIN_DIR/scripts/ensure_runtime_preflight.py" 2>/dev/null || true
fi

# ── 9. Self-verification ───────────────────────────────────────────────────
echo "  Running self-verification..."
echo ""
bash "$PLUGIN_DIR/scripts/verify_activation.sh" || true
bash "$PLUGIN_DIR/scripts/smoke_test.sh" || true

# ── 10. Telemetry: install event ───────────────────────────────────────────
VENV_PY_FOR_TELEM="$(python3 -c "import sys; sys.path.insert(0,'$PLUGIN_DIR'); from mcp_server.platform_paths import venv_python; p=venv_python(__import__('pathlib').Path('$PLUGIN_DIR')); print(p or '')")"
[ -n "$VENV_PY_FOR_TELEM" ] || VENV_PY_FOR_TELEM="$PLUGIN_DIR/.venv/bin/python"
"$VENV_PY_FOR_TELEM" - "$PLUGIN_DIR" <<'PYEOF' &
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
echo "  Backend    : $CURRENT_BACKEND  (ainl_native ready: $NATIVE_READY)"
echo "  Venv       : $PLUGIN_DIR/.venv"
echo ""
if [ "$CURRENT_BACKEND" = "python" ] && [ "$NATIVE_READY" = "true" ]; then
    echo "  To switch to native: bash scripts/upgrade_to_native.sh"
    echo ""
elif [ "$CURRENT_BACKEND" = "native" ]; then
    echo "  Native backend active. Run /reload-plugins in Claude Code if MCP was already running."
    echo ""
fi
if [ -n "$RESTORE_FROM" ]; then
    echo "  Restoring from backup: $RESTORE_FROM"
    if bash "$PLUGIN_DIR/scripts/restore_install.sh" "$RESTORE_FROM"; then
        echo "  [ok] Backup restored (config + graph_memory)"
    else
        echo "  [warn] Restore failed — see messages above" >&2
    fi
    echo ""
fi

echo "Next step: restart Claude Code."
echo ""
echo "You should see:"
echo "  • [AINL Cortex] banner at session start"
echo "  • ~30 new MCP tools under /mcp (memory + goals + ainl + a2a)"
echo ""
