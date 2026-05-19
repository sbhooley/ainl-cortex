#!/usr/bin/env bash
# Backup ainl-cortex plugin config + all Claude project graph_memory data for restore.
#
# Usage:
#   bash scripts/backup_install.sh
#   bash scripts/backup_install.sh /path/to/backup-dir
#
# Output: ~/.claude/backups/ainl-cortex-YYYYMMDD-HHMMSS/ (or custom dir)
# Restore: bash scripts/restore_install.sh <that-dir>
set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
PROJECTS_DIR="$CLAUDE_HOME/projects"
SETTINGS="$CLAUDE_HOME/settings.json"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
DEFAULT_BACKUP="$CLAUDE_HOME/backups/ainl-cortex-$TIMESTAMP"
BACKUP_DIR="${1:-$DEFAULT_BACKUP}"

mkdir -p "$BACKUP_DIR"

echo "=== AINL Cortex backup ==="
echo "  Plugin : $PLUGIN_DIR"
echo "  Target : $BACKUP_DIR"
echo ""

# Plugin config (user customizations)
if [[ -f "$PLUGIN_DIR/config.json" ]]; then
  cp "$PLUGIN_DIR/config.json" "$BACKUP_DIR/plugin-config.json"
  echo "  [ok] plugin-config.json"
fi

# Claude settings snippet (plugin registration only)
python3 - "$SETTINGS" "$BACKUP_DIR/claude-settings-ainl.json" <<'PY'
import json, pathlib, sys
src, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
snippet = {}
if src.is_file():
    try:
        s = json.loads(src.read_text())
    except (json.JSONDecodeError, OSError):
        s = {}
    snippet["enabledPlugins"] = {
        k: v for k, v in (s.get("enabledPlugins") or {}).items()
        if "ainl" in k.lower()
    }
    snippet["extraKnownMarketplaces"] = {
        k: v for k, v in (s.get("extraKnownMarketplaces") or {}).items()
        if "ainl" in k.lower()
    }
out.write_text(json.dumps(snippet, indent=2) + "\n")
PY
echo "  [ok] claude-settings-ainl.json"

# Git revision (if install is a clone)
if git -C "$PLUGIN_DIR" rev-parse HEAD >/dev/null 2>&1; then
  {
    echo "commit=$(git -C "$PLUGIN_DIR" rev-parse HEAD)"
    echo "branch=$(git -C "$PLUGIN_DIR" branch --show-current 2>/dev/null || true)"
    git -C "$PLUGIN_DIR" log -1 --oneline
  } >"$BACKUP_DIR/plugin-git.txt"
  echo "  [ok] plugin-git.txt"
fi

# All graph_memory trees (ainl_memory.db, ainl_native.db, inbox, etc.)
GM_COUNT=0
if [[ -d "$PROJECTS_DIR" ]]; then
  GM_COUNT=$(find "$PROJECTS_DIR" -type d -name graph_memory 2>/dev/null | wc -l | tr -d ' ')
fi
if [[ "$GM_COUNT" -gt 0 ]]; then
  # Archive paths as <project_id>/graph_memory/... under $PROJECTS_DIR
  (
    cd "$PROJECTS_DIR"
    # shellcheck disable=SC2044
    find . -type d -name graph_memory -print0 | xargs -0 tar -czf "$BACKUP_DIR/graph_memory.tar.gz"
  )
  echo "  [ok] graph_memory.tar.gz ($GM_COUNT project dirs)"
else
  echo "  [info] no graph_memory directories found"
  touch "$BACKUP_DIR/graph_memory.tar.gz.empty"
fi

# Manifest
STORE_BACKEND="unknown"
if [[ -f "$BACKUP_DIR/plugin-config.json" ]]; then
  STORE_BACKEND=$(python3 -c "import json; print(json.load(open('$BACKUP_DIR/plugin-config.json')).get('memory',{}).get('store_backend','unknown'))")
fi

python3 - "$BACKUP_DIR/MANIFEST.json" "$TIMESTAMP" "$PLUGIN_DIR" "$STORE_BACKEND" "$GM_COUNT" <<'PY'
import json, sys
from datetime import datetime, timezone
out, ts, plugin, backend, gm_count = sys.argv[1:6]
manifest = {
    "schema": "ainl-cortex-backup-v1",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "timestamp": ts,
    "plugin_dir": plugin,
    "memory": {"store_backend": backend, "graph_memory_project_dirs": int(gm_count)},
    "files": {
        "plugin_config": "plugin-config.json",
        "claude_settings_snippet": "claude-settings-ainl.json",
        "graph_memory_archive": "graph_memory.tar.gz",
        "plugin_git": "plugin-git.txt",
    },
    "restore": "bash scripts/restore_install.sh " + out,
}
open(out, "w").write(json.dumps(manifest, indent=2) + "\n")
PY
echo "  [ok] MANIFEST.json"
echo ""
echo "Backup complete: $BACKUP_DIR"
echo "Restore later:  cd \"$PLUGIN_DIR\" && bash scripts/restore_install.sh \"$BACKUP_DIR\""
echo "$BACKUP_DIR"
