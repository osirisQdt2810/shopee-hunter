#!/usr/bin/env python3
"""Turn ``coverage.xml`` into a shields.io endpoint payload.

Self-hosted on purpose: a badge that needs no third-party token cannot rot when that
service starts refusing uploads. ``ci.yml`` publishes the JSON this writes to an orphan
``badges`` branch, and shields.io reads it from raw.githubusercontent.

Usage:
    python scripts/coverage_badge.py coverage.xml badge/coverage.json
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Green only once the suite genuinely covers the logic; the thresholds are deliberately
# honest rather than flattering.
_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (90.0, "brightgreen"),
    (80.0, "green"),
    (70.0, "yellowgreen"),
    (60.0, "yellow"),
    (50.0, "orange"),
    (0.0, "red"),
)


def line_rate(coverage_xml: Path) -> float:
    """Read the overall line rate out of a Cobertura-format report, as a percentage."""
    try:
        root = ET.parse(coverage_xml).getroot()
    except (OSError, ET.ParseError) as exc:
        raise SystemExit(f"cannot read coverage report {coverage_xml}: {exc}") from exc
    raw = root.get("line-rate")
    if raw is None:
        raise SystemExit(
            f"{coverage_xml} has no line-rate attribute — wrong report format?"
        )
    return float(raw) * 100.0


def colour_for(percent: float) -> str:
    for floor, colour in _THRESHOLDS:
        if percent >= floor:
            return colour
    return "red"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    source, target = Path(argv[1]), Path(argv[2])
    percent = line_rate(source)
    payload = {
        "schemaVersion": 1,
        "label": "coverage",
        "message": f"{percent:.0f}%",
        "color": colour_for(percent),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload), encoding="utf-8")
    print(f"coverage {percent:.2f}% -> {target} ({payload['color']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
