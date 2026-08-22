#!/usr/bin/env python3
"""Pre-commit hook: format QML with the ``qmlformat`` that ships inside the PySide6 wheel.

The UI is QML, so it needs a formatter as much as the Python does — without one, the
Theme-token discipline drowns in whitespace diffs. Using the binary from the already-installed
wheel means no extra download and no version skew with the Qt we build against.

Skips silently (exit 0) when the binary cannot be found: a contributor without the dev extra
installed should get a lint failure from CI, not a blocked commit they cannot diagnose.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def find_qmlformat() -> Path | None:
    """Locate qmlformat inside the installed PySide6 package."""
    try:
        import PySide6
    except ImportError:
        return None

    root = Path(PySide6.__file__).resolve().parent
    # Layout differs by platform: Qt/libexec on macOS/Linux, next to the DLLs on Windows.
    candidates = [
        root / "qmlformat",
        root / "qmlformat.exe",
        root / "Qt" / "libexec" / "qmlformat",
        root / "Qt" / "bin" / "qmlformat.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = next(iter(root.rglob("qmlformat*")), None)
    return found if found and found.is_file() else None


def main(argv: list[str]) -> int:
    files = [Path(arg) for arg in argv[1:] if arg.endswith(".qml")]
    if not files:
        return 0

    binary = find_qmlformat()
    if binary is None:
        print("qmlformat not found in the installed PySide6 — skipping QML formatting.")
        print('Install the dev extra to enable it:  pip install -e ".[dev]"')
        return 0

    changed: list[Path] = []
    for path in files:
        before = path.read_bytes()
        result = subprocess.run(
            [str(binary), "--inplace", "--normalize", str(path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # A parse failure here is a real QML syntax error; show it and fail the commit.
            print(f"{path}: qmlformat failed\n{result.stderr.strip()}")
            return 1
        if path.read_bytes() != before:
            changed.append(path)

    if changed:
        print("qmlformat reformatted:")
        for path in changed:
            print(f"  {path}")
        print("\nRe-stage the files and commit again.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
