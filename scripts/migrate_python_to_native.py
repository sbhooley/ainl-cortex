#!/usr/bin/env python3
"""Cross-platform 5-phase Python → native migration (replaces bash wrapper)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp_server.platform_paths import venv_python  # noqa: E402


def main() -> int:
    py = venv_python(ROOT)
    if py is None:
        print("ERROR: .venv missing — run setup.sh or setup.ps1 first.", file=sys.stderr)
        return 2

    def run(label: str, args: list[str]) -> None:
        print(f"\n==> {label}")
        subprocess.run([str(py), *args], cwd=str(ROOT), check=True)

    try:
        print("\n==> Phase 1: ainl_native availability check")
        _run([str(py), "-c", "import ainl_native"])
        print("  ainl_native is importable.")
        run("Phase 2: dry-run migration", [str(ROOT / "migrate_to_native.py"), "--dry-run", "--strict"])
        run("Phase 3: real migration", [str(ROOT / "migrate_to_native.py"), "--strict"])
        print("\n==> Phase 4: verification")
        subprocess.run([str(py), str(ROOT / "scripts" / "verify_migration.py")], cwd=str(ROOT), check=True)
        run(
            "Phase 5: inject verify=passed and flip config",
            [
                str(ROOT / "migrate_to_native.py"),
                "--inject-verify-status",
                "passed",
            ],
        )
        subprocess.run(
            [str(py), str(ROOT / "migrate_to_native.py"), "--flip-config"],
            cwd=str(ROOT),
            check=True,
        )
    except subprocess.CalledProcessError:
        print(
            "\nERROR: migration failed. Inspect logs/migration_latest.json and "
            "logs/verify_latest.json",
            file=sys.stderr,
        )
        print(f"Roll back: {py} migrate_to_python.py --purge-native", file=sys.stderr)
        return 1

    print("\nMigration complete. Restart Claude Code or run /reload-plugins.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
