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

# ADR-002's four value kinds. Kept beside each other so extending the rule means editing one
# place here and its twin in scripts/hooks/check_layers.py.
QML_LITERAL_COLOUR = r'"#[0-9A-Fa-f]{3,8}"'

# A bare number assigned straight to a design property. An expression (`radius: width / 2`)
# is fine — it derives from geometry rather than inventing a value — so the number must be
# the whole right-hand side. Zero is exempt: `radius: 0` is the absence of rounding, not a
# design decision anyone would want to retune from Theme.qml.
QML_LITERAL_DESIGN_VALUE = re.compile(
    r"\b(?:font\.)?(?:radius|duration|pixelSize)\s*:\s*(?!0\s*$)\d+(?:\.\d+)?\s*$"
)


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


def test_qml_uses_theme_tokens_not_literal_design_values() -> None:
    """No literal colour, radius, duration or font size in QML outside Theme.qml (ADR-002).

    Platform-identical rendering and a one-file restyle both depend on this, and it is the
    single easiest rule to break by accident.

    All four of the rubric's value kinds are checked, not just colour. An earlier version
    matched hex literals only, which let `radius: 13` sit one pixel off `Theme.radiusMd` and
    a hard-coded `duration: 1200` ignore `reducedMotion` — while the checklist claimed the
    rule was machine-checked. A guard that covers a quarter of its stated rule is worse than
    no guard, because it is trusted.
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
            for match in re.finditer(QML_LITERAL_COLOUR, line):
                offenders.append(
                    f"{path.relative_to(qml_root)}:{number} {match.group(0)}"
                )
            match = QML_LITERAL_DESIGN_VALUE.search(line)
            if match:
                offenders.append(
                    f"{path.relative_to(qml_root)}:{number} {match.group(0).strip()}"
                )
    assert not offenders, (
        "literal design values in QML — add a token to Theme.qml instead:\n"
        + "\n".join(offenders)
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


@pytest.mark.parametrize(
    "line",
    [
        "        radius: 13",
        "            radius: 1.5",
        "                duration: 1200",
        "        font.pixelSize: 52",
        "            pixelSize: 18",
    ],
)
def test_the_design_value_guard_catches_each_literal_kind(line: str) -> None:
    """The guard's own regression test.

    It matched `"#RRGGBB"` and nothing else for a while, so `radius: 13` (one pixel off
    `Theme.radiusMd`) and a hard-coded `duration: 1200` (which cannot honour `reducedMotion`)
    both passed a check the PR checklist described as machine-enforced. A guard that is
    trusted and narrower than its stated rule is worse than no guard, so the coverage of the
    pattern is pinned here rather than left to be re-derived from whatever it happens to
    match today.
    """
    assert QML_LITERAL_DESIGN_VALUE.search(line)


@pytest.mark.parametrize(
    "line",
    [
        "        radius: Theme.radiusMd",
        "        radius: width / 2",
        "        duration: Theme.durFast",
        "        font.pixelSize: Theme.fontSm",
        "        radius: 0",
        "        implicitHeight: 40",
        "        height: 7",
    ],
)
def test_the_design_value_guard_allows_tokens_and_geometry(line: str) -> None:
    """A token, an expression derived from geometry, and `0` are all legitimate.

    `radius: 0` is the absence of rounding rather than a value anyone would retune centrally,
    and plain dimensions (`height`, `implicitHeight`) are layout, not theme.
    """
    assert not QML_LITERAL_DESIGN_VALUE.search(line)


def test_qml_never_branches_on_the_sale_tier_ordinal() -> None:
    """`bridge.tierLevel` is a ramp, not a category (ADR-002, ADR-006).

    Views used to ask `tierLevel >= 3` to decide whether to render a day as a big campaign.
    That hardcodes which `SaleTier` members are the loud ones: insert a tier and every such
    comparison shifts by one, so 12.12 renders as a neutral grey badge on the single day the
    app is supposed to be shouting — silently, with the suite green. Categorical questions go
    through `tierIsPeak` / `tierTone`, which are answered in core and merely displayed here.
    """
    qml_root = PACKAGE / "gui" / "qml"
    offenders: list[str] = []
    for path in qml_root.rglob("*.qml"):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if line.lstrip().startswith("//"):
                continue
            if re.search(r"tierLevel\s*(?:[<>]=?|===?|!==?)", line):
                offenders.append(f"{path.relative_to(qml_root)}:{number}")
    assert not offenders, (
        "QML compares tierLevel against a number — use bridge.tierIsPeak or "
        "bridge.tierTone instead:\n" + "\n".join(offenders)
    )
