"""Shared PyInstaller inputs, so the macOS and Windows specs cannot drift.

The failure mode this exists to prevent: a new QML file works in a dev checkout (where the
package is on ``sys.path`` and the file is simply there) and is missing from the bundle,
because someone added it to one spec and not the other. Both specs import from here, and
:func:`qml_datas` walks the tree rather than listing files.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = REPO_ROOT / "src" / "shopee_hunter"
ENTRY_POINT = str(REPO_ROOT / "packaging" / "entry.py")

APP_NAME = "Sale Hunter"
EXE_NAME = "SaleHunter"
BUNDLE_ID = "com.osirisqdt.salehunter"
VERSION = "0.1.0"


def qml_datas() -> list[tuple[str, str]]:
    """Every QML/qmldir/JS file, as ``(source, destination-dir)`` pairs.

    Walked, not enumerated: a listed file is a file someone has to remember to list.
    """
    datas: list[tuple[str, str]] = []
    qml_root = PACKAGE_DIR / "gui" / "qml"
    for path in qml_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in (".qml", ".js") and path.name != "qmldir":
            continue
        destination = Path("shopee_hunter/gui/qml") / path.parent.relative_to(qml_root)
        datas.append((str(path), str(destination)))
    return datas


def resource_datas() -> list[tuple[str, str]]:
    """Icons and any other bundled assets."""
    datas: list[tuple[str, str]] = []
    resources = PACKAGE_DIR / "resources"
    if resources.is_dir():
        for path in resources.rglob("*"):
            if path.is_file():
                destination = Path("shopee_hunter/resources") / path.parent.relative_to(
                    resources
                )
                datas.append((str(path), str(destination)))
    return datas


def config_datas() -> list[tuple[str, str]]:
    """The example settings file, so a packaged app can show a user what is configurable."""
    example = REPO_ROOT / "config" / "settings.example.toml"
    return [(str(example), "config")] if example.is_file() else []


def all_datas() -> list[tuple[str, str]]:
    return [*qml_datas(), *resource_datas(), *config_datas()]


# Qt modules Qt Quick pulls in dynamically, which PyInstaller's static analysis cannot see.
HIDDEN_IMPORTS = [
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
    "PySide6.QtQml",
    "PySide6.QtNetwork",
    "PySide6.QtOpenGL",
    "shopee_hunter.sources.affiliate_api",
    "shopee_hunter.sources.fixture",
    "shopee_hunter.sources.shopee_browser",
    "shopee_hunter.sources.shopee_web",
]

# Everything the app does not use. PySide6 is large; excluding these roughly halves the
# bundle, and each one here has been checked against an actual import.
EXCLUDES = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.Qt3DCore",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "tkinter",
    "matplotlib",
    "numpy",
    "pytest",
    "playwright",  # the optional extra is installed by the user, not shipped
]
