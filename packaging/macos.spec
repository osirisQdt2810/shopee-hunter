# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — macOS .app bundle.  Build:  python packaging/build.py
#
# Universal2 is deliberately NOT requested: PySide6 ships per-architecture wheels, so a
# universal build would need both installed side by side. Build on the architecture you ship.
#
# `SPECPATH` and `Analysis` come from PyInstaller's own namespace; ruff cannot see them, which
# is why packaging/ is excluded from F821 in pyproject.
import sys
from pathlib import Path

sys.path.insert(0, SPECPATH)

from common import (
    APP_NAME,
    BUNDLE_ID,
    ENTRY_POINT,
    EXCLUDES,
    EXE_NAME,
    HIDDEN_IMPORTS,
    PACKAGE_DIR,
    REPO_ROOT,
    VERSION,
    all_datas,
)

icon = PACKAGE_DIR / "resources" / "icon.icns"

analysis = Analysis(
    [ENTRY_POINT],
    pathex=[str(REPO_ROOT / "src")],
    binaries=[],
    datas=all_datas(),
    hiddenimports=HIDDEN_IMPORTS,
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=EXE_NAME,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon) if icon.is_file() else None,
)

collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name=EXE_NAME,
)

app = BUNDLE(
    collect,
    name=f"{APP_NAME}.app",
    icon=str(icon) if icon.is_file() else None,
    bundle_identifier=BUNDLE_ID,
    version=VERSION,
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": VERSION,
        "LSMinimumSystemVersion": "12.0",
        # The window is frameless and translucent (gui/window.py); without this, macOS
        # composites it against an opaque backing store and the glass look is lost.
        "NSHighResolutionCapable": True,
        "NSSupportsAutomaticGraphicsSwitching": True,
        # Shopee is reached over HTTPS only; no ATS exceptions are needed and none are granted.
        "NSAppTransportSecurity": {"NSAllowsArbitraryLoads": False},
        "LSApplicationCategoryType": "public.app-category.productivity",
    },
)
