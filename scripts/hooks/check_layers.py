#!/usr/bin/env python3
"""Pre-commit hook: the one-way import rule.

A cheap subset of ``tests/test_architecture.py``, run on every commit because it catches the
single most damaging mistake in this codebase — a business rule, or an I/O call, landing in
the wrong layer. By the time the full suite runs the change is already written; failing here
costs seconds.

Exit 0 clean, 1 with a violation named by file and line.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_NAME = "shopee_hunter"
PACKAGE = REPO_ROOT / "src" / PACKAGE_NAME

CORE_FORBIDDEN = ("PySide6", "httpx", "sqlite3", "playwright")
IO_LAYERS = ("sources", "storage", "services")

# ADR-002. The twin of this block lives in tests/test_architecture.py, whose docstring states
# exactly what these do and do not catch; both must move together.
QML_LITERAL_COLOUR = r'"#[0-9A-Fa-f]{3,8}"'

# `Qt.rgba(...)` from numbers alone. `Qt.rgba(Theme.accent.r, …)` derives from a token and
# survives a restyle; the all-numeric form is a hand-mixed colour that does not.
QML_LITERAL_RGBA = re.compile(
    r"Qt\.rgba\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*(?:,\s*[\d.]+\s*)?\)"
)

# A bare number as the whole right-hand side of a design property. `radius: width / 2`
# derives from geometry and is fine; `radius: 0` is the absence of rounding, not a token.
QML_LITERAL_DESIGN_VALUE = re.compile(
    r"\b(?:font\.)?(?:radius|duration|pixelSize|pointSize)\s*:\s*(?!0\s*$)\d+(?:\.\d+)?\s*$"
)

# The same, hidden in a ternary branch: `font.pixelSize: cond ? 8 : Theme.fontSm`.
QML_LITERAL_TERNARY = re.compile(
    r"\b(?:font\.)?(?:radius|duration|pixelSize|pointSize)\s*:.*\?\s*"
    r"(?:(?!0\s*:)\d+(?:\.\d+)?\s*:|[^:?]*:\s*(?!0\s*$)\d+(?:\.\d+)?\s*$)"
)

# Named CSS colours. `"white"` slipped past the hex pattern for the whole life of this guard.
# Curated rather than exhaustive, and `transparent` is deliberately absent: it means "no
# colour at all" and is used 17 times as a legitimate structural value, not a design choice.
QML_LITERAL_NAMED_COLOUR = re.compile(
    r':\s*"(?:white|black|red|green|blue|yellow|orange|purple|pink|cyan|magenta|brown'
    r'|grey|gray|lime|navy|teal|silver|gold|maroon|olive|aqua|fuchsia)"',
    re.IGNORECASE,
)

QML_LITERAL_PATTERNS = (
    QML_LITERAL_COLOUR,
    QML_LITERAL_NAMED_COLOUR,
    QML_LITERAL_RGBA,
    QML_LITERAL_DESIGN_VALUE,
    QML_LITERAL_TERNARY,
)


def top_level_imports(path: Path) -> list[tuple[int, str]]:
    """``(lineno, module)`` for every import, relative ones prefixed with a dot."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        print(f"{path}: syntax error at line {exc.lineno}: {exc.msg}")
        raise SystemExit(1) from exc

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(
                (node.lineno, alias.name.split(".")[0]) for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            # The FULL dotted module, not just its root. Reducing to the root meant
            # `from shopee_hunter.gui.bridge import AppBridge` inside services/ resolved to
            # "shopee_hunter", which matches neither ".gui" nor "PySide6" — so the hook and
            # the test both passed while the one-way rule was broken. An absolute import of
            # our own package is normalised to the relative form so one rule covers both.
            module = node.module or ""
            if node.level:
                found.append((node.lineno, f".{module}" if module else "."))
            elif module == PACKAGE_NAME or module.startswith(f"{PACKAGE_NAME}."):
                found.append((node.lineno, "." + module[len(PACKAGE_NAME) + 1 :]))
            else:
                found.append((node.lineno, module))
    return found


def main() -> int:
    if not PACKAGE.is_dir():
        return 0

    violations: list[str] = []

    for path in (PACKAGE / "core").rglob("*.py"):
        for lineno, module in top_level_imports(path):
            if module in CORE_FORBIDDEN:
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}: core/ must not import {module!r} — "
                    f"core/ is pure logic; move the I/O to sources/, storage/ or services/"
                )
            if any(
                module == f".{layer}" or module.startswith(f".{layer}.")
                for layer in (*IO_LAYERS, "gui")
            ):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}: core/ must not import {module!r} — "
                    f"core/ depends on nothing else in the package"
                )

    for layer in IO_LAYERS:
        for path in (PACKAGE / layer).rglob("*.py"):
            for lineno, module in top_level_imports(path):
                if (
                    module == "PySide6"
                    or module == ".gui"
                    or module.startswith(".gui.")
                ):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{lineno}: {layer}/ must not import "
                        f"{module!r} — orchestration has to stay callable from a script"
                    )

    # A Deal constructed in gui/ means the GUI decided what a deal is (ADR-005).
    for path in (PACKAGE / "gui").rglob("*.py"):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if re.search(r"\bDeal\s*\(", line) and "DealListModel" not in line:
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{number}: gui/ constructs a Deal — only "
                    f"core/deals.py may (ADR-005)"
                )

    # Literal design values in QML defeat the Theme singleton (ADR-002) — all four kinds the
    # ADR names, not just colour.
    theme = PACKAGE / "gui" / "qml" / "Theme" / "Theme.qml"
    for path in (PACKAGE / "gui" / "qml").rglob("*.qml"):
        if path == theme:
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if line.lstrip().startswith("//"):
                continue
            for pattern in QML_LITERAL_PATTERNS:
                match = re.search(pattern, line)
                if match:
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{number}: literal "
                        f"{match.group(0).strip()} — add a token to Theme.qml instead "
                        f"(ADR-002)"
                    )

    if violations:
        print("Layer boundary violations:\n")
        for violation in violations:
            print(f"  {violation}")
        print("\nSee .claude/CONVENTIONS.md Part 2 — 'The three-layer rule'.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
