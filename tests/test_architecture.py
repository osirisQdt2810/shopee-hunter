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

# ADR-002's value kinds. Kept beside each other so extending the rule means editing one place
# here and its twin in scripts/hooks/check_layers.py.
QML_LITERAL_COLOUR = r'"#[0-9A-Fa-f]{3,8}"'

# `Qt.rgba(...)` built entirely from numbers. This codebase's own idiom for *deriving* a
# colour is `Qt.rgba(Theme.accent.r, …)`, which stays correct through a restyle; the
# all-numeric form is a hand-mixed colour that does not, and matching quoted hex alone could
# never see it. Requiring every argument to be numeric is what keeps the derived form legal.
QML_LITERAL_RGBA = re.compile(
    r"Qt\.rgba\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*(?:,\s*[\d.]+\s*)?\)"
)

# A bare number as the whole right-hand side of a design property. An expression
# (`radius: width / 2`, `duration: Theme.durAmbient / 4`) is fine: it derives from geometry
# or from a token, so it still moves when the theme does. Zero is exempt — `radius: 0` is the
# absence of rounding, not a value anyone would retune centrally.
QML_LITERAL_DESIGN_VALUE = re.compile(
    r"\b(?:font\.)?(?:radius|duration|pixelSize|pointSize)\s*:\s*(?!0\s*$)\d+(?:\.\d+)?\s*$"
)

# The same value hiding in a ternary branch — `font.pixelSize: cond ? 8 : Theme.fontSm`.
# Worth its own pattern because the anchored rule above requires the number to be the entire
# RHS, and a conditional is the natural place a per-case size gets written by hand.
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


def _imports(path: Path) -> set[str]:
    """Top-level module names imported by a file, from its AST rather than a regex."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # The FULL dotted module, not just its root, and an absolute import of our own
            # package normalised to the relative form. Reducing to the root let
            # `from shopee_hunter.gui.bridge import AppBridge` inside services/ resolve to
            # "shopee_hunter" and match nothing — the rule was unenforced for every absolute
            # self-import, which is the spelling an IDE's auto-import produces.
            module = node.module or ""
            if node.level:
                names.add(f".{module}" if module else ".")
            elif module == "shopee_hunter" or module.startswith("shopee_hunter."):
                names.add("." + module[len("shopee_hunter") + 1 :])
            else:
                names.add(module)
    return names


def _reaches(names: set[str], layer: str) -> bool:
    """Does this file import `layer`, as a package or as any module inside it?"""
    return any(name == f".{layer}" or name.startswith(f".{layer}.") for name in names)


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
    names = _imports(path)
    offenders = [layer for layer in (*IO_LAYERS, "gui") if _reaches(names, layer)]
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
    assert not _reaches(names, "gui") and "PySide6" not in names, (
        f"{path.relative_to(PACKAGE)} depends on the GUI layer. Orchestration must be callable "
        f"from a script (scripts/live_check.py does exactly that)."
    )


def test_gui_holds_no_deal_logic() -> None:
    """A Deal may only be constructed by core.deals — nowhere in gui/.

    The check is narrow on purpose: it looks for the *construction*, which is the thing that
    would mean the GUI decided what a deal is.
    """
    engine = PACKAGE / "core" / "deals.py"
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == engine:
            continue
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"\bDeal\s*\(", source), (
            f"{path.relative_to(PACKAGE)} constructs a Deal. Only core/deals.py may — every "
            f"other layer renders or routes verdicts, it does not make them (ADR-005). The "
            f"scan used to cover gui/ alone, so a Deal built in services/ was unguarded."
        )


def test_qml_uses_theme_tokens_not_literal_design_values() -> None:
    """Literal design values in QML outside Theme.qml (ADR-002).

    Platform-identical rendering and a one-file restyle both depend on this, and it is the
    single easiest rule to break by accident.

    WHAT THIS ACTUALLY CATCHES, stated precisely because two earlier versions of this
    docstring claimed more than the patterns delivered:

    * quoted hex colours, and `Qt.rgba(...)` whose arguments are all numeric;
    * radius / duration / pixelSize / pointSize given a bare number as the whole RHS;
    * the same value hidden in a ternary branch.

    WHAT IT DOES NOT CATCH, deliberately: a literal used as an operand of an otherwise
    derived expression — `Theme.durAmbient / 4`, `width / 2`, `Theme.fontXs - 1`. Those still
    move when the theme moves, which is the property ADR-002 protects. The cost of that
    exemption is that a magic constant can hide inside a larger expression:
    `Math.max(600, Theme.durSlow * 2)` did exactly that, and defeated `reducedMotion` by
    flooring an animation at 600ms. No regex separates a scaling factor from a magic number
    reliably, so that case is caught in review — and this docstring says so instead of
    implying the check is total.
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
            for pattern in QML_LITERAL_PATTERNS:
                match = re.search(pattern, line)
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
        "        font.pointSize: 11",
        # Hand-mixed colours: quoted hex, and the Qt.rgba form hex-matching could never see.
        '        color: "#FF5722"',
        "        border.color: Qt.rgba(1, 1, 1, 0.35)",
        "        shadowColor: Qt.rgba(0, 0, 0, 0.45)",
        "        color: Qt.rgba(0.02, 0.03, 0.06, 0.68)",
        # The same design value hiding in a ternary branch.
        "        font.pixelSize: parent.traffic ? 8 : Theme.fontSm",
        "        radius: hovered ? Theme.radiusSm : 12",
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
    assert any(re.search(pattern, line) for pattern in QML_LITERAL_PATTERNS)


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
        # Derived from a token or from geometry: still moves when the theme moves.
        "        duration: Theme.durAmbient / 4",
        "        font.pixelSize: Theme.fontXs - 1",
        "        radius: parent.radius - 1",
        # Qt.rgba built FROM a token is the codebase's idiom and must stay legal.
        "        color: Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.42)",
        # Zero is the absence of rounding, in a ternary as much as on its own.
        "        radius: maximised ? 0 : Theme.windowRadius",
        "        font.pixelSize: big ? Theme.fontXl : Theme.fontSm",
    ],
)
def test_the_design_value_guard_allows_tokens_and_geometry(line: str) -> None:
    """A token, an expression derived from geometry, and `0` are all legitimate.

    `radius: 0` is the absence of rounding rather than a value anyone would retune centrally,
    and plain dimensions (`height`, `implicitHeight`) are layout, not theme.
    """
    assert not any(re.search(pattern, line) for pattern in QML_LITERAL_PATTERNS)


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


def test_every_dealcard_property_is_wired_by_the_delegate() -> None:
    """A property DealCard declares but DealsView never assigns is dead plumbing.

    This is not hypothetical tidiness. `genuine` — the deal engine's headline verdict, the
    single judgement this whole app exists to make — was declared on the card, exposed by the
    model, assigned by the delegate, and then read by nothing, so a listing the engine had
    rejected rendered identically to one it had verified. A role can be added, plumbed and
    forgotten in three separate files without one test noticing, which is exactly the shape
    of mistake a structural check catches and a behavioural one does not.
    """
    qml_root = PACKAGE / "gui" / "qml"
    card = (qml_root / "components" / "DealCard.qml").read_text(encoding="utf-8")
    view = (qml_root / "views" / "DealsView.qml").read_text(encoding="utf-8")

    declared = set(re.findall(r"^\s*property\s+\w+\s+(\w+)\s*:", card, re.MULTILINE))
    # `index` comes from the delegate's own context, not from the model.
    declared -= {"index"}

    unwired = {
        name
        for name in declared
        if not re.search(rf"^\s*{name}\s*:", view, re.MULTILINE)
    }
    assert (
        not unwired
    ), f"DealCard declares but DealsView never assigns: {sorted(unwired)}"

    # Comments are stripped before counting uses. Leaving them in makes the check trivially
    # satisfiable by the very comment explaining what the property is for — which is exactly
    # what happened the first time this test was run against the bug it was written for.
    code = "\n".join(
        line for line in card.splitlines() if not line.lstrip().startswith("//")
    )
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)

    unread = set()
    for name in declared:
        # A property is "read" if it appears anywhere other than its own declaration line.
        uses = len(re.findall(rf"\b(?:card\.)?{name}\b", code))
        if uses <= 1:
            unread.add(name)
    assert not unread, (
        f"DealCard declares properties nothing in the component reads: {sorted(unread)}. "
        f"Either render the value or stop plumbing it."
    )
