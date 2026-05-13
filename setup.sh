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

# ── 2. Create venv + install dependencies ──────────────────────────────────
echo "  Creating Python venv..."
python3 -m venv "$PLUGIN_DIR/.venv"
"$PLUGIN_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$PLUGIN_DIR/.venv/bin/pip" install --quiet -r "$PLUGIN_DIR/requirements-ainl.txt"
echo "  [ok] Dependencies installed"

# ── 3. Configure config.json with safe defaults ────────────────────────────
echo "  Configuring plugin..."
python3 - "$PLUGIN_DIR" <<'PYEOF'
import json, pathlib, sys

plugin_dir = pathlib.Path(sys.argv[1])
config_path = plugin_dir / "config.json"

with open(config_path) as f:
    cfg = json.load(f)

# Safe default: Python backend works for everyone
cfg.setdefault("memory", {})["store_backend"] = "python"

# A2A bridge is an advanced feature requiring separate setup — off by default
cfg.setdefault("a2a", {})["enabled"] = False
cfg["a2a"].pop("bridge_script", None)  # remove any machine-specific path

# Upgrade to native backend automatically if Rust toolchain is available
# (ainl-* crates are published on crates.io — no local armaraos clone needed)
import shutil as _shutil
if _shutil.which("rustc"):
    cfg["memory"]["store_backend"] = "native"
    print("    rustc found — enabling native Rust backend (ainl-* crates from crates.io)")
else:
    print("    python backend selected (install Rust from https://rustup.rs to enable native backend)")

# Generate a stable anonymous install ID (once; preserved on re-runs)
import uuid as _uuid
cfg.setdefault("install_id", str(_uuid.uuid4()))

# Remote telemetry — opt-out via "telemetry": {"remote": {"enabled": false}}
cfg.setdefault("telemetry", {}).setdefault("remote", {}).setdefault("enabled", True)

with open(config_path, "w") as f:
    json.dump(cfg, f, indent=2)
print("    config.json written")
PYEOF
echo "  [ok] Config updated"

# ── 4. Set up local marketplace (symlink so git pull takes effect immediately) ──
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

# ── 5. Register plugin in ~/.claude/settings.json ──────────────────────────
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

# ── Self-verification ──────────────────────────────────────────────────────
echo "  Running self-verification..."
echo ""

# Structural check (files, venv, registration)
bash "$PLUGIN_DIR/scripts/verify_activation.sh" || true

# Runtime check (actually exercises all memory subsystems)
bash "$PLUGIN_DIR/scripts/smoke_test.sh" || true

# ── Telemetry: install event (fire-and-forget, respects opt-out) ───────────
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
BACKEND=$(python3 -c "import json; print(json.load(open('$PLUGIN_DIR/config.json'))['memory']['store_backend'])")
echo "=== Setup complete! ==="
echo ""
echo "  Plugin dir : $PLUGIN_DIR"
echo "  Backend    : $BACKEND"
echo "  Venv       : $PLUGIN_DIR/.venv"
echo ""
echo "Next step: restart Claude Code."
echo ""
echo "You should see:"
echo "  • [AINL Cortex] banner at session start"
echo "  • ~30 new MCP tools under /mcp (memory + goals + ainl + a2a)"
echo ""
