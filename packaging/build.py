#!/usr/bin/env python3
"""Build the desktop bundle for the current OS.

    python packaging/build.py            # -> dist/
    python packaging/build.py --dmg      # macOS: also produce a .dmg
    python packaging/build.py --clean    # remove build/ and dist/ first

One spec per OS (``packaging/macos.spec``, ``packaging/windows.spec``), both importing
``packaging/common.py`` so the file lists cannot diverge — a QML file present in one spec and
absent from the other is a bug that only appears after a build.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPECS = {"darwin": "macos.spec", "win32": "windows.spec"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--clean", action="store_true", help="remove build/ and dist/ first"
    )
    parser.add_argument(
        "--dmg", action="store_true", help="macOS only: wrap the .app in a .dmg"
    )
    args = parser.parse_args(argv)

    spec_name = SPECS.get(sys.platform)
    if spec_name is None:
        print(
            f"No packaging spec for {sys.platform}. The app ships on macOS and Windows;"
        )
        print("run it from source elsewhere:  python -m shopee_hunter")
        return 2

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print(
            'PyInstaller is not installed. Add the packaging extra:  pip install -e ".[package]"'
        )
        return 2

    if args.clean:
        for directory in (REPO_ROOT / "build", REPO_ROOT / "dist"):
            if directory.exists():
                shutil.rmtree(directory)
                print(f"removed {directory}")

    spec = REPO_ROOT / "packaging" / spec_name
    print(f"building with {spec.name} …\n")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", str(spec)],
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        return result.returncode

    produced = sorted((REPO_ROOT / "dist").glob("*"))
    print("\nbuilt:")
    for path in produced:
        print(f"  {path}")

    if args.dmg and sys.platform == "darwin":
        return _make_dmg()

    print(
        "\nSmoke-test the bundle before shipping it — a missing QML file only fails here:"
    )
    if sys.platform == "darwin":
        print('  open "dist/Sale Hunter.app"')
    else:
        print(r"  dist\SaleHunter\SaleHunter.exe")
    return 0


def _make_dmg() -> int:
    """Wrap the .app in a compressed disk image using hdiutil (always present on macOS)."""
    app = REPO_ROOT / "dist" / "Sale Hunter.app"
    if not app.exists():
        print(f"{app} not found — build first")
        return 1
    dmg = REPO_ROOT / "dist" / "SaleHunter.dmg"
    dmg.unlink(missing_ok=True)
    result = subprocess.run(
        [
            "hdiutil",
            "create",
            "-volname",
            "Sale Hunter",
            "-srcfolder",
            str(app),
            "-ov",
            "-format",
            "UDZO",
            str(dmg),
        ]
    )
    if result.returncode == 0:
        print(f"\nwrote {dmg}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
