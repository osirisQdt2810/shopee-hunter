#!/usr/bin/env python3
"""Run the app from a checkout, optionally reloading QML on change.

The reload loop exists because styling is iterative: without it, every colour tweak costs an
app restart, a re-scan, and the loss of whatever view you were looking at.

    python scripts/run_dev.py                 # just run it
    python scripts/run_dev.py --reload        # restart on any .qml change
    python scripts/run_dev.py --demo --reload  # …with the offline catalogue
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
QML_DIR = REPO_ROOT / "src" / "shopee_hunter" / "gui" / "qml"


def qml_signature() -> tuple[tuple[str, float], ...]:
    """Path+mtime of every QML file — cheap enough to poll, exact enough to trust."""
    return tuple(
        sorted((str(path), path.stat().st_mtime) for path in QML_DIR.rglob("*.qml"))
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--reload", action="store_true", help="restart the app when a .qml file changes"
    )
    parser.add_argument("--demo", action="store_true", help="offline demo catalogue")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=0.7)
    args = parser.parse_args(argv)

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    if args.reload:
        env["SALEHUNTER_QML_HOT_RELOAD"] = "true"

    command = [sys.executable, "-m", "shopee_hunter"]
    if args.demo:
        command.append("--demo")
    if args.verbose:
        command.append("--verbose")

    if not args.reload:
        return subprocess.call(command, env=env, cwd=REPO_ROOT)

    print("QML hot reload: watching", QML_DIR)
    print("(the app restarts on change; Ctrl+C to stop)\n")
    while True:
        signature = qml_signature()
        process = subprocess.Popen(command, env=env, cwd=REPO_ROOT)
        try:
            while process.poll() is None:
                time.sleep(args.poll_seconds)
                if qml_signature() != signature:
                    print("\n--- QML changed, restarting ---\n")
                    process.terminate()
                    process.wait(timeout=5)
                    break
            else:
                # The app exited on its own (window closed, or a crash) — stop watching.
                return process.returncode or 0
        except KeyboardInterrupt:
            process.terminate()
            process.wait(timeout=5)
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
