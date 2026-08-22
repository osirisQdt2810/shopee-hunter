"""The layering rules, enforced rather than hoped for.

CONVENTIONS Part 2 states the import direction; this file is why it holds. Every one of these
assertions corresponds to a mistake that is easy to make, invisible in review, and expensive
later:

* ``core/`` importing Qt makes the deal engine untestable without a display;
* ``core/`` importing httpx or sqlite3 makes "pure logic" a lie and invites I/O into a
  function that is called in a loop;
* a service importing ``gui/`` inverts the dependency and drags Qt into every scan;
* a business rule in a QML file means the app's central claim lives somewhere no test can
  reach it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "shopee_hunter"

# Modules core/ may never import. `sqlite3` is in here as much for design as for testing: if
# the deal engine can reach a database, it will eventually query one.
CORE_FORBIDDEN = ("PySide6", "httpx", "sqlite3", "playwright", "respx")

# Layers that own I/O. They may use core/, never gui/.
IO_LAYERS = ("sources", "storage", "services")


def _imports(path: Path) -> set[str]:
    """Top-level module names imported by a file, from its AST rather than a regex."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level:
            # Relative import: record the package it reaches into, so `from ..gui import x`
            # inside services/ is visible as a gui dependency.
            names.add(f".{node.module.split('.')[0]}" if node.module else ".")
    return names


def _python_files(subpackage: str) -> list[Path]:
    return sorted((PACKAGE / subpackage).rglob("*.py"))


@pytest.mark.parametrize("path", _python_files("core"), ids=lambda p: p.name)
def test_core_is_pure(path: Path) -> None:
    """core/ must not import Qt, HTTP, sqlite, or a browser driver."""
    offenders = _imports(path) & set(CORE_FORBIDDEN)
    assert not offenders, (
        f"{path.relative_to(PACKAGE)} imports {sorted(offenders)}. core/ is pure logic — move "
        f"the I/O into sources/, storage/ or services/."
    )


@pytest.mark.parametrize("path", _python_files("core"), ids=lambda p: p.name)
def test_core_does_not_import_siblings(path: Path) -> None:
    """core/ must not reach into any other layer of the package."""
    relative = {name for name in _imports(path) if name.startswith(".")}
    forbidden = {f".{layer}" for layer in (*IO_LAYERS, "gui")}
    offenders = relative & forbidden
    assert (
        not offenders
    ), f"{path.relative_to(PACKAGE)} imports {sorted(offenders)} — core/ depends on nothing"


@pytest.mark.parametrize(
    "path",
    [p for layer in IO_LAYERS for p in _python_files(layer)],
    ids=lambda p: f"{p.parent.name}/{p.name}",
)
def test_io_layers_do_not_import_gui(path: Path) -> None:
    """sources/, storage/ and services/ must not depend on the GUI."""
    names = _imports(path)
    assert ".gui" not in names and "PySide6" not in names, (
        f"{path.relative_to(PACKAGE)} depends on the GUI layer. Orchestration must be callable "
        f"from a script (scripts/live_check.py does exactly that)."
    )


def test_gui_holds_no_deal_logic() -> None:
    """A Deal may only be constructed by core.deals — nowhere in gui/.

    The check is narrow on purpose: it looks for the *construction*, which is the thing that
    would mean the GUI decided what a deal is.
    """
    for path in _python_files("gui"):
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"\bDeal\s*\(", source), (
            f"{path.relative_to(PACKAGE)} constructs a Deal. Only core/deals.py may — the GUI "
            f"renders verdicts, it does not make them (ADR-005)."
        )


def test_qml_uses_theme_tokens_not_literal_colours() -> None:
    """No hex colour literals in QML outside the Theme singleton (ADR-002).

    Platform-identical rendering and a one-file restyle both depend on this, and it is the
    single easiest rule to break by accident.
    """
    qml_root = PACKAGE / "gui" / "qml"
    theme_file = qml_root / "Theme" / "Theme.qml"
    offenders: list[str] = []
    for path in qml_root.rglob("*.qml"):
        if path == theme_file:
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if line.lstrip().startswith("//"):
                continue
            for match in re.finditer(r'"#[0-9A-Fa-f]{3,8}"', line):
                offenders.append(
                    f"{path.relative_to(qml_root)}:{number} {match.group(0)}"
                )
    assert (
        not offenders
    ), "literal colours in QML — add a token to Theme.qml instead:\n" + "\n".join(
        offenders
    )


def test_every_qml_file_is_registered_in_its_qmldir() -> None:
    """A QML component not listed in its directory's qmldir is invisible to `import`.

    This fails at runtime, silently, as "Type X unavailable" — and only in whichever view
    happens to use it.
    """
    qml_root = PACKAGE / "gui" / "qml"
    for qmldir in qml_root.rglob("qmldir"):
        listed = {
            line.split()[-1]
            for line in qmldir.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("module")
        }
        present = {path.name for path in qmldir.parent.glob("*.qml")}
        missing = present - listed
        assert (
            not missing
        ), f"{qmldir.relative_to(qml_root)} does not list {sorted(missing)}"
