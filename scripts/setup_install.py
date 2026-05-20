#!/usr/bin/env python3
"""
Cross-platform AINL Cortex install (venv, deps, config, manifest).

Invoked by setup.sh (macOS/Linux) and setup.ps1 (Windows). Safe to re-run.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_server.platform_paths import (  # noqa: E402
    find_system_python,
    hook_command,
    is_windows,
    os_family,
    plugin_root,
    venv_pip,
    venv_python,
    write_install_manifest,
)

HOOK_SCRIPTS = (
    "startup",
    "user_prompt_submit",
    "ainl_detection",
    "user_prompt_expansion",
    "post_tool_use",
    "ainl_validator",
    "pre_compact",
    "post_compact",
    "stop",
)


def _run(cmd: list, *, cwd: Path, env: dict | None = None) -> None:
    subprocess.run(cmd, cwd=str(cwd), env=env or os.environ, check=True)


def create_venv(root: Path, py: Path) -> None:
    vpy = venv_python(root)
    if vpy is not None:
        print(f"  [ok] venv exists: {vpy}")
        return
    print(f"  Creating Python venv ({os_family()})...")
    _run([str(py), "-m", "venv", str(root / ".venv")], cwd=root)
    vpy = venv_python(root)
    if vpy is None:
        raise RuntimeError(f"venv creation failed under {root / '.venv'}")
    print(f"  [ok] venv: {vpy}")


def pip_install(root: Path) -> None:
    pip = venv_pip(root)
    vpy = venv_python(root)
    if not pip or not vpy:
        raise RuntimeError("venv pip/python not found")
    print("  Installing dependencies...")
    _run([str(pip), "install", "--quiet", "--upgrade", "pip"], cwd=root)
    req = root / "requirements-ainl.txt"
    _run([str(pip), "install", "--quiet", "-r", str(req)], cwd=root)
    print("  [ok] Dependencies installed")


def configure_config(root: Path) -> None:
    from mcp_server.config_loader import (
        LOCAL_CONFIG_FILENAME,
        migrate_install_id_to_local,
        write_local_config,
    )

    print("  Configuring plugin...")
    migrate_install_id_to_local(root)
    config_path = root / "config.json"
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("memory", {})
    if cfg["memory"].get("store_backend") not in ("python", "native"):
        cfg["memory"]["store_backend"] = "python"
    cfg["memory"].setdefault("project_isolation_mode", "per_repo")
    cfg.setdefault("a2a", {})
    cfg["a2a"].setdefault("enabled", False)
    cfg["a2a"].pop("bridge_script", None)
    cfg.setdefault("telemetry", {}).setdefault("remote", {}).setdefault("enabled", True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    local_path = root / LOCAL_CONFIG_FILENAME
    local_cfg = {}
    if local_path.is_file():
        with open(local_path, encoding="utf-8") as f:
            local_cfg = json.load(f)
    local_cfg.setdefault("install_id", str(uuid.uuid4()))
    write_local_config(root, local_cfg)
    print(
        f"  [ok] config.json store_backend={cfg['memory']['store_backend']!r} "
        f"project_isolation_mode={cfg['memory'].get('project_isolation_mode')!r}"
    )


def install_ainl_native(root: Path, *, python_only: bool) -> bool:
    print("  Installing ainl_native (PyPI wheel when available)...")
    vpy = venv_python(root)
    pip = venv_pip(root)
    if not vpy or not pip:
        return False
    min_ver = os.environ.get("AINL_NATIVE_MIN_VERSION", "0.1.1")
    try:
        _run([str(pip), "install", "--quiet", "--upgrade", f"ainl_native>={min_ver}"], cwd=root)
        _run([str(vpy), "-c", "import ainl_native; print(ainl_native.__file__)"], cwd=root)
        print("  [ok] ainl_native from PyPI")
        return True
    except subprocess.CalledProcessError:
        print("  [warn] ainl_native not installed — Python backend still works")
        return False


def write_hooks_json(root: Path) -> None:
    """Emit hooks.json with OS-agnostic run_hook.py commands."""
    hooks = {
        "description": "AINL-inspired graph memory system for Claude Code - execution becomes memory",
        "hooks": {},
    }
    hook_lists = {
        "SessionStart": ["startup"],
        "UserPromptSubmit": ["user_prompt_submit", "ainl_detection"],
        "UserPromptExpansion": ["user_prompt_expansion"],
        "PostToolUse": ["post_tool_use", "ainl_validator"],
        "PreCompact": ["pre_compact"],
        "PostCompact": ["post_compact"],
        "Stop": ["stop"],
    }
    timeouts = {
        "startup": 20,
        "user_prompt_submit": 5,
        "ainl_detection": 3,
        "user_prompt_expansion": 3,
        "post_tool_use": 3,
        "ainl_validator": 5,
        "pre_compact": 3,
        "post_compact": 3,
        "stop": 5,
    }
    for event, scripts in hook_lists.items():
        entries = []
        for script in scripts:
            entries.append(
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": hook_command(script, root),
                            "timeout": timeouts.get(script, 5),
                        }
                    ]
                }
            )
        hooks["hooks"][event] = entries

    path = root / "hooks" / "hooks.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hooks, f, indent=2)
        f.write("\n")
    print(f"  [ok] hooks/hooks.json ({os_family()} commands via run_hook.py)")


def run_preflight(root: Path) -> None:
    vpy = venv_python(root)
    if not vpy:
        return
    script = root / "scripts" / "ensure_runtime_preflight.py"
    if script.is_file():
        subprocess.run([str(vpy), str(script)], cwd=str(root), check=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AINL Cortex cross-platform install")
    parser.add_argument("--plugin-dir", type=Path, default=ROOT)
    parser.add_argument("--python-only", action="store_true", help="Skip native backend upgrade prompts")
    parser.add_argument(
        "--register-claude",
        action="store_true",
        help="Register local marketplace + enable plugin in ~/.claude/settings.json",
    )
    args = parser.parse_args(argv)

    root = plugin_root(args.plugin_dir)
    print(f"=== AINL Cortex setup ({os_family()}) ===")
    print(f"  Plugin: {root}")

    py = find_system_python()
    if py is None:
        print(
            "ERROR: Python 3.10+ not found. Install from https://www.python.org/downloads/\n"
            "       On Windows, check 'Add python.exe to PATH' during install.",
            file=sys.stderr,
        )
        return 1

    create_venv(root, py)
    pip_install(root)
    configure_config(root)
    native_ok = install_ainl_native(root, python_only=args.python_only)
    write_hooks_json(root)
    from mcp_server.mcp_launcher_config import configure_mcp_launcher

    configure_mcp_launcher(root)
    manifest = write_install_manifest(root, ainl_native_ready=native_ok)
    run_preflight(root)

    if args.register_claude:
        from mcp_server.install_bootstrap import register_claude_integration

        reg_ok, reg_msg = register_claude_integration(root)
        if reg_ok:
            print(f"  [ok] Claude Code registration: {reg_msg}")
        else:
            print(f"  [warn] Claude Code registration: {reg_msg}")

    print("")
    print("=== Python install steps complete ===")
    print(f"  Platform     : {manifest.get('platform')} ({manifest.get('platform_release')})")
    print(f"  Venv Python  : {manifest.get('venv_python')}")
    print(f"  ainl_native  : {'yes' if native_ok else 'no (optional)'}")
    print("")
    if is_windows():
        print("  Windows: MCP uses mcp_launch.py (no Git Bash required for the server).")
        print("  Hooks use scripts/run_hook.py with your PATH python.")
    print("  Next: restart Claude Code, then /reload-plugins if upgrading.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
