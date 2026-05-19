#!/usr/bin/env bash
# Restore graph_memory + plugin config from backup_install.sh output.
#
# Usage:
#   bash scripts/restore_install.sh ~/.claude/backups/ainl-cortex-YYYYMMDD-HHMMSS
#   bash scripts/restore_install.sh <backup-dir> --config-only
#   bash scripts/restore_install.sh <backup-dir> --memory-only
set -euo pipefail

if [[ $# -lt 1 ]] || [[ "${1:-}" == "-h" ]] || [[ "${1:-}" == "--help" ]]; then
  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

BACKUP_DIR="$(cd "$1" && pwd)"
shift
PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
PROJECTS_DIR="$CLAUDE_HOME/projects"
SETTINGS="$CLAUDE_HOME/settings.json"

CONFIG_ONLY=false
MEMORY_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --config-only) CONFIG_ONLY=true ;;
    --memory-only) MEMORY_ONLY=true ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [[ ! -f "$BACKUP_DIR/MANIFEST.json" ]]; then
  echo "error: not a backup dir (missing MANIFEST.json): $BACKUP_DIR" >&2
  exit 1
fi

echo "=== AINL Cortex restore ==="
echo "  From   : $BACKUP_DIR"
echo "  Plugin : $PLUGIN_DIR"
echo ""

if [[ "$MEMORY_ONLY" != "true" ]]; then
  if [[ -f "$BACKUP_DIR/plugin-config.json" ]]; then
    cp "$BACKUP_DIR/plugin-config.json" "$PLUGIN_DIR/config.json"
    echo "  [ok] restored plugin config.json"
  fi

  if [[ -f "$BACKUP_DIR/claude-settings-ainl.json" ]]; then
    python3 - "$SETTINGS" "$BACKUP_DIR/claude-settings-ainl.json" <<'PY'
import json, pathlib, sys
settings_path, snippet_path = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
snippet = json.loads(snippet_path.read_text())
settings = {}
if settings_path.is_file():
    try:
        settings = json.loads(settings_path.read_text())
    except (json.JSONDecodeError, OSError):
        settings = {}
settings.setdefault("enabledPlugins", {}).update(snippet.get("enabledPlugins") or {})
settings.setdefault("extraKnownMarketplaces", {}).update(snippet.get("extraKnownMarketplaces") or {})
settings_path.parent.mkdir(parents=True, exist_ok=True)
settings_path.write_text(json.dumps(settings, indent=2) + "\n")
PY
    echo "  [ok] merged Claude settings (ainl plugin registration)"
  fi
fi

if [[ "$CONFIG_ONLY" != "true" ]]; then
  if [[ -f "$BACKUP_DIR/graph_memory.tar.gz" ]]; then
    mkdir -p "$PROJECTS_DIR"
    tar -xzf "$BACKUP_DIR/graph_memory.tar.gz" -C "$PROJECTS_DIR"
    echo "  [ok] restored graph_memory archives under $PROJECTS_DIR"
  elif [[ -f "$BACKUP_DIR/graph_memory.tar.gz.empty" ]]; then
    echo "  [info] backup had no graph_memory data"
  else
    echo "  [warn] no graph_memory.tar.gz in backup" >&2
  fi
fi

echo ""
echo "Restore complete. Restart Claude Code if it is running."
if [[ -f "$BACKUP_DIR/plugin-git.txt" ]]; then
  echo "Backed-up plugin revision:"
  cat "$BACKUP_DIR/plugin-git.txt"
fi
