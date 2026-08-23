"""Environment switches for development. Never secrets.

Anything a developer flips while debugging lives here as a documented constant, so a stray
``os.getenv`` does not appear in the middle of feature code. User-facing configuration goes
through ``core.settings`` (which reads ``SALEHUNTER_*`` env vars for the settings tree
itself); this module is only for switches that have no place in a settings file.
"""

from __future__ import annotations

import os

ENV_PREFIX = "SALEHUNTER_"


def _flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(f"{ENV_PREFIX}{name}", "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _text(name: str, default: str = "") -> str:
    return os.environ.get(f"{ENV_PREFIX}{name}", default).strip()


# Serve the demo catalogue and skip every network call. Also set by `--demo`.
DEMO_MODE = _flag("DEMO_MODE")

# Reload QML from disk on change (scripts/run_dev.py --reload). Off in a packaged build,
# where the QML is inside the bundle and cannot be edited anyway.
QML_HOT_RELOAD = _flag("QML_HOT_RELOAD")

# Log every QML warning as an error and exit non-zero on the first one. What CI uses, so a
# broken binding fails the build instead of rendering an empty panel.
QML_STRICT = _flag("QML_STRICT")

# Override the SQLite path — used by tests and by `--data-dir`.
DATA_DIR_OVERRIDE = _text("DATA_DIR")

# Extra logging.
VERBOSE = _flag("VERBOSE")
