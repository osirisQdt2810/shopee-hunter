#!/usr/bin/env bash
# The offline test suite — ONE definition, so ci.yml, pr-pipeline.yml and a developer's
# terminal cannot drift apart. Extra pytest args are passed straight through, which is how
# the coverage job adds its flags without duplicating the invocation.
#
#   bash scripts/run_tests.sh
#   bash scripts/run_tests.sh --cov=src/shopee_hunter --cov-report=xml
#
# This runs the OFFLINE tier only (`-m "not live"` comes from pyproject's addopts). The live
# tier is deliberately not here: it needs the real site and a real window, so it is a human's
# pre-PR step (`pytest -m live`, `scripts/live_check.py`) — see ADR-008.
set -euo pipefail

cd "$(dirname "$0")/.."

# Qt needs a platform plugin even for a headless smoke-load of a QML view. `offscreen`
# renders into memory, so the GUI tests run identically on a CI runner with no display and
# on a developer's machine without stealing focus.
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
# Turn QML warnings into visible output; a silent QML binding error is the most common way a
# view "passes" while rendering nothing (ADR-002).
export QT_LOGGING_RULES="${QT_LOGGING_RULES:-qt.qml.binding.removal.info=true}"
# Deterministic, tz-independent runs: sale-day maths converts to ICT explicitly, so a runner
# in another zone must not change a single assertion.
export TZ="${TZ:-UTC}"
# Never let a test read the developer's real settings or price history.
export SALEHUNTER_DEMO_MODE=true

# Find an interpreter. `python` exists in an activated venv and on CI runners, but a bare
# `bash scripts/run_tests.sh` from a shell without the venv activated has only `python3` — and
# "python: command not found" reads like a broken script rather than a missing activation.
# $PYTHON wins so a caller can pin one.
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in ./.venv/bin/python python python3; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
  done
fi
if [ -z "$PY" ]; then
  echo "No Python interpreter found. Activate the venv or set PYTHON=/path/to/python." >&2
  exit 127
fi

echo "python: $("$PY" --version 2>&1)  |  platform: $QT_QPA_PLATFORM  |  TZ: $TZ"
exec "$PY" -m pytest "$@"
