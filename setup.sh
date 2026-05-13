#!/usr/bin/env bash
# setup.sh — Install and activate ainl-cortex for Claude Code.
# Run once after cloning: bash setup.sh
# Safe to re-run — all steps are idempotent.
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
SETTINGS="$HOME/.claude/settings.json"
MARKETPLACE="$HOME/.claude/ainl-local-marketplace"

echo ""
echo "=== AINL Cortex — Setup ==="
echo ""
echo "  What this script does:"
echo "    1. Checks Python 3.10+"
echo "    2. Installs Rust (enables the native backend with richer session memory)"
echo "       → If Rust install fails, falls back to the Python backend automatically"
echo "    3. Creates a Python venv and installs dependencies"
echo "    4. Builds the ainl_native Rust extension (if Rust available)"
echo "    5. Migrates any existing memory data if switching backends"
echo "    6. Registers the plugin with Claude Code"
echo "    7. Runs verification tests"
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

# ── 2. Rust check + auto-install ───────────────────────────────────────────
RUST_AVAILABLE=false
if command -v rustc >/dev/null 2>&1; then
    RUST_AVAILABLE=true
    RUST_VER=$(rustc --version | cut -d' ' -f2)
    echo "  [ok] Rust $RUST_VER (native backend available)"
elif command -v curl >/dev/null 2>&1; then
    echo "  Rust not found — installing via rustup (official installer from https://rustup.rs)..."
    if curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
        | sh -s -- -y --no-modify-path 2>&1 | grep -E "^(info|warning|error|  Rust)"; then
        source "$HOME/.cargo/env" 2>/dev/null || true
        if command -v rustc >/dev/null 2>&1; then
            RUST_AVAILABLE=true
            echo "  [ok] Rust $(rustc --version | cut -d' ' -f2) installed"
        fi
    fi
    if [ "$RUST_AVAILABLE" = "false" ]; then
        echo "  [warn] Rust install failed — using Python backend (tip: install manually from https://rustup.rs)"
    fi
else
    echo "  [warn] Rust not found and curl unavailable — using Python backend (tip: install from https://rustup.rs)"
fi

# ── 3. Create venv + install dependencies ──────────────────────────────────
echo "  Creating Python venv..."
python3 -m venv "$PLUGIN_DIR/.venv"
"$PLUGIN_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$PLUGIN_DIR/.venv/bin/pip" install --quiet -r "$PLUGIN_DIR/requirements-ainl.txt"
echo "  [ok] Dependencies installed"

# ── 4. Configure config.json ───────────────────────────────────────────────
echo "  Configuring plugin..."

# Capture previous backend before any changes (for migration detection)
PREV_BACKEND=$(python3 -c "
import json, pathlib
p = pathlib.Path('$PLUGIN_DIR') / 'config.json'
try:
    print(json.loads(p.read_text()).get('memory', {}).get('store_backend', 'python'))
except:
    print('python')
")

python3 - "$PLUGIN_DIR" "$RUST_AVAILABLE" <<'PYEOF'
import json, pathlib, sys

plugin_dir = pathlib.Path(sys.argv[1])
rust_available = sys.argv[2] == "true"
config_path = plugin_dir / "config.json"

with open(config_path) as f:
    cfg = json.load(f)

# Safe default: Python backend
cfg.setdefault("memory", {})["store_backend"] = "python"

# A2A bridge off by default (requires separate daemon setup)
cfg.setdefault("a2a", {})["enabled"] = False
cfg["a2a"].pop("bridge_script", None)

if rust_available:
    cfg["memory"]["store_backend"] = "native"
    print("    rustc found — enabling native Rust backend (ainl-* crates from crates.io)")
else:
    print("    python backend selected (install Rust from https://rustup.rs to enable native backend)")

# Generate stable anonymous install ID (once; preserved on re-runs)
import uuid as _uuid
cfg.setdefault("install_id", str(_uuid.uuid4()))

# Remote telemetry — opt-out via "telemetry": {"remote": {"enabled": false}}
cfg.setdefault("telemetry", {}).setdefault("remote", {}).setdefault("enabled", True)

with open(config_path, "w") as f:
    json.dump(cfg, f, indent=2)
print("    config.json written")
PYEOF
echo "  [ok] Config updated"

# ── 5. Build native extension (must happen before migration) ───────────────
NEW_BACKEND=$(python3 -c "import json; print(json.load(open('$PLUGIN_DIR/config.json'))['memory']['store_backend'])")

NATIVE_BUILT=false
if [ "$NEW_BACKEND" = "native" ]; then
    echo "  Building ainl_native Rust extension..."
    "$PLUGIN_DIR/.venv/bin/pip" install maturin --quiet 2>/dev/null || true
    if PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
        "$PLUGIN_DIR/.venv/bin/maturin" develop --release \
        --manifest-path "$PLUGIN_DIR/ainl_native/Cargo.toml" 2>&1 | tail -2; then
        NATIVE_BUILT=true
        echo "  [ok] ainl_native built"
    else
        echo "  [warn] ainl_native build failed — reverting to Python backend"
        python3 -c "
import json; p='$PLUGIN_DIR/config.json'
cfg=json.load(open(p)); cfg.setdefault('memory',{})['store_backend']='python'
open(p,'w').write(json.dumps(cfg,indent=2))
"
        NEW_BACKEND="python"
    fi
fi

# ── 6. Migrate memory if switching Python → Native ─────────────────────────
if [ "$PREV_BACKEND" = "python" ] && [ "$NEW_BACKEND" = "native" ] && [ "$NATIVE_BUILT" = "true" ]; then
    HAS_DATA=$(python3 -c "
import pathlib
dbs = list(pathlib.Path.home().glob('.claude/projects/*/graph_memory/ainl_memory.db'))
print('yes' if dbs else 'no')
")
    if [ "$HAS_DATA" = "yes" ]; then
        echo "  Existing memory data found — migrating to native backend..."
        echo "  (Python DBs kept as backups at ~/.claude/projects/*/graph_memory/ainl_memory.db)"
        MIGRATION_OUT=$("$PLUGIN_DIR/.venv/bin/python" "$PLUGIN_DIR/migrate_to_native.py" 2>&1)
        echo "$MIGRATION_OUT"
        # Check for error count in migration output
        ERRORS=$(echo "$MIGRATION_OUT" | grep -c "^  !" || true)
        if [ "$ERRORS" -gt 0 ]; then
            echo "  [warn] $ERRORS node(s)/edge(s) failed to migrate — partial migration, Python backup intact"
        else
            echo "  [ok] Memory migrated to native backend"
            # Reset upgrade-hint counter so Python tip never appears on native
            python3 -c "
import json; p='$PLUGIN_DIR/config.json'
cfg=json.load(open(p)); cfg.pop('python_upgrade_hint_shown', None)
open(p,'w').write(json.dumps(cfg,indent=2))
"
        fi
    else
        echo "  No existing memory to migrate — starting fresh with native backend"
    fi
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
echo "  Backend    : $NEW_BACKEND"
echo "  Venv       : $PLUGIN_DIR/.venv"
echo ""
echo "Next step: restart Claude Code."
echo ""
echo "You should see:"
echo "  • [AINL Cortex] banner at session start"
echo "  • ~30 new MCP tools under /mcp (memory + goals + ainl + a2a)"
echo ""
