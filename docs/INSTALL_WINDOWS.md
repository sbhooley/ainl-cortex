# Windows install (Claude Code)

AINL Cortex detects the OS during install and writes `install_manifest.json` at the plugin root with `platform`, `venv_python`, and related paths.

## Pre-install checklist (Windows 11)

Before you install, confirm:

| Check | Why |
|-------|-----|
| **Network** for first install | Plugin downloads **uv** + Python 3.12 (no manual python.org visit) |
| **Python on PATH** (optional) | If already installed, setup is faster; not required |
| Run **`setup.ps1` from a permanent folder** (not `%TEMP%`) | Avoids marketplace junction pointing at a throwaway clone |
| **PowerShell 5.1+** (default on Win11) | `setup.ps1` uses Python for `settings.json` (not `ConvertFrom-Json -AsHashtable`) |
| **Git for Windows** (optional) | Only if you use `bash setup.sh` instead of `setup.ps1` |
| **Restart Claude Code** after setup | Hooks + MCP pick up `.venv\Scripts\python.exe` |

If MCP fails with “python not found”, point the host at `mcp_launch.cmd` or ensure `python` / `py` is on PATH; `mcp_launch.cmd` tries venv → `python` → `py -3` → `python3`.

**A2A logging** is off by default. Enabling A2A on Windows is supported (no Unix-only `fcntl` lock).

## Zero-touch install (recommended)

When you enable the plugin, **the first MCP start or session hook** can create `.venv`, install deps, and register marketplace settings automatically — you do not need to run `setup.ps1` manually if Python is already on PATH.

For a clean install in chat, ask Claude:

```
Install https://github.com/sbhooley/ainl-cortex on this Windows machine using
py -3 scripts\claude_install.py (or setup.ps1), register it, then tell me to restart
and run /reload-plugins.
```

## Automatic install (agent or manual)

Claude should run **one** of:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1 -PythonOnly
```

Or from Git Bash:

```bash
bash setup.sh --python-only
```

Both call `scripts/setup_install.py`, which:

1. Finds Python 3.10+ (`python`, `py`, or common install paths)
2. Creates `.venv` with `Scripts\python.exe` on Windows
3. Installs dependencies and optional `ainl_native` PyPI wheel
4. Regenerates `hooks/hooks.json` to use `scripts/run_hook.py` (no hard-coded `.venv/bin`)
5. Writes `install_manifest.json`

## How OS detection works

| Layer | Mechanism |
|-------|-----------|
| Install | `sys.platform == "win32"` → `os_family() == "windows"` in `mcp_server/platform_paths.py` |
| Manifest | `install_manifest.json` records platform + absolute `venv_python` after setup |
| MCP | `plugin.json` launches `python …/mcp_launch.py` (re-execs `.venv\Scripts\python.exe`) |
| Hooks | `hooks.json` → `py -3 …/scripts/run_hook.py <hook>` on Windows (`python3` on macOS/Linux) |
| Fallback | `mcp_launch.cmd` if a host needs a `.cmd` entry point |

## Requirements on Windows 11

- **Python 3.10+** from [python.org](https://www.python.org/downloads/) with **Add to PATH**
- Claude Code (plugin marketplace or local clone under `%USERPROFILE%\.claude\plugins\ainl-cortex`)
- No WSL required for core memory + MCP (optional for ArmaraOS A2A daemon)

## Verify

After restart:

1. `[AINL Cortex]` banner at session start
2. `/mcp` lists `ainl-cortex__*` tools
3. `install_manifest.json` shows `"platform": "windows"` and a `venv_python` under `Scripts`

## Native Rust backend (optional, full performance)

The **Python backend** is the default and works on all Windows installs. The **native backend** uses the `ainl_native` extension (Rust + SQLite) for faster graph memory.

### What Windows users need

| Path | Rust required? |
|------|----------------|
| **PyPI wheel** (recommended) | **No** — CI publishes `ainl_native` wheels for `windows-latest` |
| **Build from source** (maturin) | **Yes** — [rustup.rs](https://rustup.rs) + Visual Studio C++ build tools |

### Fresh install → native in one step

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1 -EnableNative -Yes
```

This runs `setup_install.py`, then `upgrade_to_native.py` (install wheel → greenfield flip or 5-phase migration).

### Python backend already installed → upgrade later

**No existing graph memory** (greenfield):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/upgrade_to_native.ps1 -Yes
```

**Existing graph memory** (migrates `ainl_memory.db` → `ainl_native.db` per project):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/upgrade_to_native.ps1 -Yes
```

Same flow as macOS/Linux: dry-run → atomic migrate → verify → flip `config.json` → `/reload-plugins`.

Cross-platform entry (if `python` is on PATH):

```powershell
cd $env:USERPROFILE\.claude\plugins\ainl-cortex
python scripts\upgrade_to_native.py --yes
```

### Claude agent playbook

```powershell
cd $env:USERPROFILE\.claude\plugins\ainl-cortex
python scripts\native_upgrade_status.py
python scripts\native_upgrade_status.py --execute
```

Or ask the user to run `/reload-plugins` after a successful upgrade.

### Rollback to Python

```powershell
python migrate_to_python.py --purge-native
```

Then set `memory.store_backend` back to `"python"` (the rollback script documents full steps — see `scripts/MIGRATION.md`).

## Fresh re-clone (when `git pull` is not enough)

Usually **`git pull` + `.\setup.cmd -PythonOnly`** is enough. Re-clone only if the tree is corrupted or you need a clean `.venv`.

1. **Quit Claude Code completely** (file locks on the plugin folder).
2. Optional — release stray MCP children:
   ```powershell
   Get-Process python*, py* -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*ainl-cortex*" } | Stop-Process -Force
   ```
3. Remove the clone (both paths if you use the local marketplace junction):
   ```powershell
   Remove-Item -Recurse -Force "$env:USERPROFILE\.claude\plugins\ainl-cortex" -ErrorAction SilentlyContinue
   ```
   Marketplace registration can keep pointing at `%USERPROFILE%\.claude\ainl-local-marketplace\plugins\ainl-cortex`; re-run setup so the junction target exists again.
4. Re-clone and install:
   ```powershell
   git clone https://github.com/sbhooley/ainl-cortex.git "$env:USERPROFILE\.claude\plugins\ainl-cortex"
   cd "$env:USERPROFILE\.claude\plugins\ainl-cortex"
   .\setup.cmd -PythonOnly
   ```
5. Restart Claude Code → `/reload-plugins`.

`settings.json` and marketplace entries are **not** removed by re-clone if you only delete the plugin directory.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| PostToolUse hook: `scripts\.\scripts\bootstrap_no_python.ps1` does not exist | Fixed in `run_hook.cmd` (use `git pull` or re-clone). Old batch logic set plugin root to `...\scripts\.` |
| `Remove-Item`: directory in use | Quit Claude Code; stop `python`/`py` under `ainl-cortex`; retry |
| `python` not found | Reinstall Python with PATH enabled; reopen terminal |
| MCP stack FAIL | `powershell -File setup.ps1` then `/reload-plugins` |
| Hooks silent | Re-run setup; confirm `hooks/hooks.json` contains `run_hook.py` |
| Stale MCP banner | `/reload-plugins` or full quit; see `docs/SELF_HEALING.md` |
| `ainl_native` install failed | Try `python scripts/upgrade_to_native.py --yes`; if no wheel, install Rust from rustup.rs and retry with `--prefer-source` |
| Migration failed | Read `logs/migration_latest.json`; do not flip config; rollback per `scripts/MIGRATION.md` |
