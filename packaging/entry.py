"""PyInstaller entry point.

A file of its own rather than ``-m shopee_hunter``: PyInstaller freezes a script, and
``python -m`` semantics (``__main__`` re-executing the package) do not survive freezing
cleanly. This keeps the frozen entry trivial and the module entry untouched.
"""

from __future__ import annotations

import multiprocessing
import sys

if __name__ == "__main__":
    # Required on Windows and on macOS's spawn start method: without it, any child process
    # re-runs the whole app and the user gets a second window.
    multiprocessing.freeze_support()

    from shopee_hunter.app import main

    sys.exit(main())
