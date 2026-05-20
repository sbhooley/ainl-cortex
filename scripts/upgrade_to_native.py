#!/usr/bin/env python3
"""
Cross-platform upgrade to the Rust native graph-memory backend.

Windows: PyPI ``ainl_native`` wheel (no Rust required in most cases).
Optional source build needs Rust + Visual Studio Build Tools (see docs).

Usage:
  python scripts/upgrade_to_native.py
  python scripts/upgrade_to_native.py --yes
  python scripts/upgrade_to_native.py --auto-install-rust
  python scripts/upgrade_to_native.py --skip-migrate
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_server.native_upgrade_runbook import graph_memory_has_data  # noqa: E402
from mcp_server.platform_paths import (  # noqa: E402
    is_windows,
    os_family,
    venv_pip,
    venv_python,
)


def _run(cmd: list, *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        check=check,
        text=True,
        capture_output=not check,
    )


def install_ainl_native(root: Path, *, prefer_source: bool = False) -> bool:
    """PyPI wheel first; maturin fallback when Rust is available."""
    py = venv_python(root)
    pip = venv_pip(root)
    if not py or not pip:
        print("ERROR: venv missing — run setup first.", file=sys.stderr)
        return False

    min_ver = os.environ.get("AINL_NATIVE_MIN_VERSION", "0.1.1")
    manifest = root / "ainl_native" / "Cargo.toml"

    def verify() -> bool:
        try:
            _run([str(py), "-c", "import ainl_native"], check=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def pip_install() -> bool:
        print(f"  Installing ainl_native>={min_ver} from PyPI...")
        try:
            _run([str(pip), "install", "--quiet", "--upgrade", f"ainl_native>={min_ver}"])
            return verify()
        except subprocess.CalledProcessError:
            return False

    def maturin_build() -> bool:
        if not shutil.which("rustc") or not shutil.which("cargo"):
            return False
        print("  Building ainl_native from source (maturin)...")
        try:
            _run([str(pip), "install", "--quiet", "maturin>=1.0,<2.0"], check=False)
            env = {**os.environ, "PYO3_USE_ABI3_FORWARD_COMPATIBILITY": "1"}
            _run(
                [str(py), "-m", "maturin", "develop", "--release", "--manifest-path", str(manifest)],
                env=env,
            )
            return verify()
        except subprocess.CalledProcessError:
            return False

    if prefer_source:
        if maturin_build() or pip_install():
            print("  [ok] ainl_native installed")
            return True
    else:
        if pip_install() or maturin_build():
            print("  [ok] ainl_native installed")
            return True

    print("  [error] ainl_native not available (no PyPI wheel and no Rust build)", file=sys.stderr)
    if is_windows():
        print(
            "  Windows: install Rust from https://rustup.rs (or winget install Rustlang.Rustup), "
            "then re-run this script.",
            file=sys.stderr,
        )
    return False


def try_install_rust() -> bool:
    if shutil.which("rustc"):
        print(f"  [ok] Rust {subprocess.check_output(['rustc', '--version'], text=True).strip()}")
        return True

    print("  [info] Rust not on PATH — PyPI wheel may still work")

    if is_windows():
        print("  [info] To build from source on Windows, install Rust: https://rustup.rs")
        print("        (Visual Studio C++ build tools are required for maturin.)")
        try_install = os.environ.get("AINL_CORTEX_AUTO_INSTALL_RUST", "").lower() in (
            "1",
            "true",
            "yes",
        )
        if not try_install:
            return False
        print("  Downloading rustup-init.exe...")
        try:
            with tempfile.TemporaryDirectory() as td:
                exe = Path(td) / "rustup-init.exe"
                urllib.request.urlretrieve(
                    "https://win.rustup.rs/x86_64",
                    exe,
                )
                subprocess.run([str(exe), "-y", "--no-modify-path"], check=True)
            cargo_bin = Path.home() / ".cargo" / "bin"
            os.environ["PATH"] = f"{cargo_bin}{os.pathsep}{os.environ.get('PATH', '')}"
            return shutil.which("rustc") is not None
        except Exception as exc:
            print(f"  [warn] rustup install failed: {exc}")
            return False

    if shutil.which("curl"):
        print("  Installing Rust via rustup (curl)...")
        try:
            subprocess.run(
                "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path",
                shell=True,
                check=True,
            )
            cargo_env = Path.home() / ".cargo" / "env"
            if cargo_env.is_file():
                # Best-effort: extend PATH for this process
                for line in cargo_env.read_text(encoding="utf-8").splitlines():
                    if line.startswith("export PATH="):
                        path_val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        os.environ["PATH"] = f"{path_val}:{os.environ.get('PATH', '')}"
            return shutil.which("rustc") is not None
        except subprocess.CalledProcessError:
            return False
    return False


def current_backend(root: Path) -> str:
    with open(root / "config.json", encoding="utf-8") as f:
        return json.load(f)["memory"].get("store_backend", "python")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upgrade AINL Cortex to native backend")
    parser.add_argument("--yes", "-y", action="store_true", help="Non-interactive (migrate without prompt)")
    parser.add_argument("--auto-install-rust", action="store_true", help="Try to install Rust when missing")
    parser.add_argument("--skip-migrate", action="store_true", help="Install ainl_native only; skip migration")
    parser.add_argument("--prefer-source", action="store_true", help="Prefer maturin build over PyPI")
    args = parser.parse_args(argv)

    if args.auto_install_rust:
        os.environ["AINL_CORTEX_AUTO_INSTALL_RUST"] = "1"

    py = venv_python(ROOT)
    if py is None:
        print("ERROR: run setup.sh or setup.ps1 first (.venv missing).", file=sys.stderr)
        return 2

    print("")
    print(f"=== AINL Cortex — Upgrade to native backend ({os_family()}) ===")
    print("")

    backend = current_backend(ROOT)
    if backend == "native":
        print("  [ok] store_backend is already native.")
        from mcp_server.mcp_reload import request_mcp_reload

        request_mcp_reload(ROOT, reason="already_native")
        print("  Run /reload-plugins in Claude Code if MCP was started before this check.")
        return 0

    if args.auto_install_rust:
        try_install_rust()

    if not install_ainl_native(ROOT, prefer_source=args.prefer_source):
        return 1

    has_data = graph_memory_has_data()

    if has_data and not args.skip_migrate:
        if not args.yes and sys.stdin.isatty():
            print("")
            print("  Existing graph memory under %USERPROFILE%\\.claude\\projects\\*\\graph_memory\\")
            print("  Migration: dry-run → migrate → verify → flip config.")
            confirm = input("  Proceed? [y/N] ").strip().lower()
            if confirm not in ("y", "yes"):
                print("  Aborted — Python backend unchanged.")
                return 0
        elif not args.yes:
            print(
                "ERROR: graph memory exists; re-run with --yes (non-interactive).",
                file=sys.stderr,
            )
            return 2

    if args.skip_migrate:
        print("  [--skip-migrate] Skipping migration.")
    elif has_data:
        print("  Running 5-phase migration...")
        r = subprocess.run([str(py), str(ROOT / "scripts" / "migrate_python_to_native.py")], cwd=str(ROOT))
        if r.returncode != 0:
            return r.returncode
    else:
        print("  No graph memory data — greenfield native flip.")
        r = subprocess.run([str(py), str(ROOT / "scripts" / "native_greenfield_flip.py")], cwd=str(ROOT))
        if r.returncode != 0:
            return r.returncode

    if current_backend(ROOT) != "native":
        print(f"ERROR: store_backend still {current_backend(ROOT)!r}", file=sys.stderr)
        return 1

    print("  [ok] store_backend = native")
    from mcp_server.mcp_reload import request_mcp_reload

    request_mcp_reload(ROOT, reason="upgrade_to_native")
    print("")
    print("=== Native upgrade complete ===")
    print("  Next: /reload-plugins in Claude Code (or fully restart)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
