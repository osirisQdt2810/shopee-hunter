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
PACKAGE = REPO_ROOT / "src" / "shopee_hunter"

CORE_FORBIDDEN = ("PySide6", "httpx", "sqlite3", "playwright")
IO_LAYERS = ("sources", "storage", "services")


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
            name = (node.module or "").split(".")[0]
            found.append((node.lineno, f".{name}" if node.level else name))
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
            if module in {f".{layer}" for layer in (*IO_LAYERS, "gui")}:
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}: core/ must not import {module!r} — "
                    f"core/ depends on nothing else in the package"
                )

    for layer in IO_LAYERS:
        for path in (PACKAGE / layer).rglob("*.py"):
            for lineno, module in top_level_imports(path):
                if module in (".gui", "PySide6"):
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

    # Literal colours in QML defeat the Theme singleton (ADR-002).
    theme = PACKAGE / "gui" / "qml" / "Theme" / "Theme.qml"
    for path in (PACKAGE / "gui" / "qml").rglob("*.qml"):
        if path == theme:
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if line.lstrip().startswith("//"):
                continue
            match = re.search(r'"#[0-9A-Fa-f]{3,8}"', line)
            if match:
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{number}: literal colour {match.group(0)} — "
                    f"add a token to Theme.qml instead (ADR-002)"
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
