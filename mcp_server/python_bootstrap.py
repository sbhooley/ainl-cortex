"""
Install Python + plugin venv when no interpreter is on PATH.

Uses the standalone `uv` binary (no existing Python required for download on
Windows via PowerShell, macOS/Linux via curl). Falls back to winget (Windows)
or brew (macOS) when uv fails.

Opt out: ``AINL_CORTEX_SKIP_PYTHON_BOOTSTRAP=1``
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path
from typing import Optional, Tuple
from urllib.request import urlopen

from .platform_paths import find_system_python, is_windows, venv_python

logger = logging.getLogger(__name__)

# Pinned for reproducible CI; bump when upgrading uv in docs.
UV_VERSION = "0.6.14"
PYTHON_VERSION = "3.12"
_BOOTSTRAP_ATTEMPTED: dict[str, float] = {}
_COOLDOWN_SEC = 300.0


def bootstrap_enabled() -> bool:
    return os.environ.get("AINL_CORTEX_SKIP_PYTHON_BOOTSTRAP", "").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    )


def bootstrap_dir(root: Path) -> Path:
    return root / ".ainl-bootstrap"


def uv_install_dir(root: Path) -> Path:
    return bootstrap_dir(root) / "uv"


def _uv_exe(root: Path) -> Path:
    return uv_install_dir(root) / ("uv.exe" if is_windows() else "uv")


def _uv_release_asset() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows":
        arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
        return f"uv-{arch}-pc-windows-msvc.zip"
    if system == "darwin":
        arch = "aarch64" if machine == "arm64" else "x86_64"
        return f"uv-{arch}-apple-darwin.tar.gz"
    if machine in ("arm64", "aarch64"):
        return "uv-aarch64-unknown-linux-gnu.tar.gz"
    if machine in ("armv7l", "armv6l"):
        return "uv-armv7-unknown-linux-gnueabihf.tar.gz"
    return "uv-x86_64-unknown-linux-gnu.tar.gz"


def _uv_download_url() -> str:
    asset = _uv_release_asset()
    return (
        f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/{asset}"
    )


def _download_file(url: str, dest: Path, timeout: int = 180) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urlopen(url, timeout=timeout) as resp:
            data = resp.read()
        dest.write_bytes(data)
        return dest.is_file() and dest.stat().st_size > 100_000
    except Exception as exc:
        logger.warning("download failed %s: %s", url, exc)
        return False


def _extract_uv_archive(archive: Path, install_root: Path) -> bool:
    install_root.mkdir(parents=True, exist_ok=True)
    name = archive.name.lower()
    try:
        if name.endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(install_root)
        elif name.endswith((".tar.gz", ".tgz")):
            with tarfile.open(archive) as tf:
                tf.extractall(install_root)
        else:
            return False
    except (OSError, zipfile.BadZipFile, tarfile.TarError) as exc:
        logger.warning("extract failed: %s", exc)
        return False

    expected = install_root / ("uv.exe" if is_windows() else "uv")
    if expected.is_file():
        return True
    for candidate in install_root.rglob("uv*"):
        if candidate.is_file() and candidate.name in ("uv", "uv.exe"):
            if candidate != expected:
                shutil.copy2(candidate, expected)
            try:
                expected.chmod(0o755)
            except OSError:
                pass
            return expected.is_file()
    return False


def ensure_uv_binary(root: Path) -> Optional[Path]:
    """Download and extract uv if missing. Returns path to uv executable."""
    uv = _uv_exe(root)
    if uv.is_file():
        return uv.resolve()

    install_root = uv_install_dir(root)
    install_root.mkdir(parents=True, exist_ok=True)
    url = _uv_download_url()
    archive = install_root / Path(url).name

    if not archive.is_file():
        if is_windows():
            ps = (
                f"$ProgressPreference='SilentlyContinue'; "
                f"Invoke-WebRequest -Uri '{url}' -OutFile '{archive}' -UseBasicParsing"
            )
            try:
                subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                    check=False,
                    timeout=180,
                    capture_output=True,
                )
            except (subprocess.TimeoutExpired, OSError):
                pass
        if not archive.is_file():
            if not _download_file(url, archive):
                return None

    if not _extract_uv_archive(archive, install_root):
        return None

    uv = _uv_exe(root)
    if uv.is_file():
        try:
            uv.chmod(0o755)
        except OSError:
            pass
        return uv.resolve()
    return None


def bootstrap_venv_with_uv(root: Path) -> Tuple[bool, str]:
    """``uv python install`` + ``uv venv`` under *root*."""
    uv = ensure_uv_binary(root)
    if uv is None:
        return False, "could not download uv"

    py_dir = bootstrap_dir(root) / "pythons"
    py_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["UV_PYTHON_INSTALL_DIR"] = str(py_dir)

    for args, label in (
        (["python", "install", PYTHON_VERSION], "uv python install"),
        (
            [
                "venv",
                str(root / ".venv"),
                "--python",
                PYTHON_VERSION,
                "--seed",
            ],
            "uv venv",
        ),
    ):
        try:
            proc = subprocess.run(
                [str(uv), *args],
                cwd=str(root),
                env=env,
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, f"{label} timed out"
        except OSError as exc:
            return False, f"{label} failed: {exc}"
        if proc.returncode != 0:
            tail = ((proc.stderr or "") + (proc.stdout or "")).strip()[-400:]
            return False, f"{label} exit {proc.returncode}: {tail}"

    vpy = venv_python(root)
    if vpy is None:
        return False, "uv finished but .venv python not found"
    return True, f"Python {PYTHON_VERSION} + venv via uv ({vpy})"


def _bootstrap_winget() -> Tuple[bool, str]:
    if not is_windows():
        return False, "winget not applicable"
    winget = shutil.which("winget")
    if not winget:
        return False, "winget not on PATH"
    pkg = "Python.Python.3.12"
    try:
        proc = subprocess.run(
            [
                winget,
                "install",
                "-e",
                "--id",
                pkg,
                "--accept-package-agreements",
                "--accept-source-agreements",
                "--disable-interactivity",
            ],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    if proc.returncode != 0:
        tail = ((proc.stderr or "") + (proc.stdout or "")).strip()[-300:]
        return False, f"winget failed: {tail}"
    # Refresh PATH discovery
    time.sleep(2)
    if find_system_python():
        return True, "Python installed via winget"
    return False, "winget reported success but python not found yet (restart terminal)"


def _bootstrap_brew() -> Tuple[bool, str]:
    if platform.system() != "Darwin":
        return False, "brew not applicable"
    brew = shutil.which("brew")
    if not brew:
        return False, "Homebrew not installed"
    try:
        proc = subprocess.run(
            [brew, "install", f"python@{PYTHON_VERSION}"],
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    if proc.returncode != 0:
        tail = ((proc.stderr or "") + (proc.stdout or "")).strip()[-300:]
        return False, f"brew install failed: {tail}"
    if find_system_python():
        return True, "Python installed via Homebrew"
    return False, "brew finished but python not on PATH"


def bootstrap_python(root: Path, *, force: bool = False) -> Tuple[bool, str]:
    """
    Ensure an interpreter exists to build ``.venv``.

    Order: existing PATH → uv (no prior Python) → winget (Win) → brew (macOS).
    """
    if not bootstrap_enabled():
        return False, "Python bootstrap disabled (AINL_CORTEX_SKIP_PYTHON_BOOTSTRAP)"

    if find_system_python() and venv_python(root):
        return True, "python and venv already present"

    key = str(root.resolve())
    now = time.time()
    if not force and key in _BOOTSTRAP_ATTEMPTED and (now - _BOOTSTRAP_ATTEMPTED[key]) < _COOLDOWN_SEC:
        if find_system_python() or venv_python(root):
            return True, "python available after recent bootstrap"
        return False, "python bootstrap failed recently; retry in a few minutes"

    _BOOTSTRAP_ATTEMPTED[key] = now

    if find_system_python() is None:
        ok, msg = bootstrap_venv_with_uv(root)
        if ok:
            return True, msg
        logger.info("uv bootstrap failed (%s), trying OS package managers", msg)

        if is_windows():
            ok, msg = _bootstrap_winget()
            if ok:
                return True, msg

        if platform.system() == "Darwin":
            ok, msg = _bootstrap_brew()
            if ok:
                return True, msg

        return False, (
            "Could not install Python automatically. "
            "Allow the plugin to download uv (network), approve winget/UAC on Windows, "
            "or install Python 3.10+ from https://www.python.org/downloads/ "
            "(enable Add to PATH)."
        )

    return True, "system Python available"


def ensure_python_for_install(root: Path) -> Tuple[bool, str]:
    """Called before setup_install when venv is missing."""
    if venv_python(root) is not None:
        return True, "venv ready"
    if find_system_python() is not None:
        return True, "system python on PATH"
    return bootstrap_python(root)
