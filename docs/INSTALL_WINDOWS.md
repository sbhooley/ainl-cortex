# Windows install (Claude Code)

AINL Cortex detects the OS during install and writes `install_manifest.json` at the plugin root with `platform`, `venv_python`, and related paths.

## Automatic install (recommended)

Ask Claude Code:

```
Install the plugin at https://github.com/sbhooley/ainl-cortex for me, then tell me when to restart.
```

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
| Hooks | `hooks.json` → `python scripts/run_hook.py <hook>` (same re-exec pattern) |
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

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `python` not found | Reinstall Python with PATH enabled; reopen terminal |
| MCP stack FAIL | `powershell -File setup.ps1` then `/reload-plugins` |
| Hooks silent | Re-run setup; confirm `hooks/hooks.json` contains `run_hook.py` |
| Stale MCP banner | `/reload-plugins` or full quit; see `docs/SELF_HEALING.md` |
