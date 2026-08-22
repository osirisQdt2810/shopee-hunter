# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — Windows one-folder build.  Build:  python packaging/build.py
#
# One FOLDER, not one file: a one-file build unpacks Qt to a temp directory on every launch,
# which costs seconds of startup and trips some antivirus heuristics. The installer story is
# a folder plus a shortcut.
import sys
from pathlib import Path

sys.path.insert(0, SPECPATH)

from common import (
    ENTRY_POINT,
    EXCLUDES,
    EXE_NAME,
    HIDDEN_IMPORTS,
    PACKAGE_DIR,
    REPO_ROOT,
    VERSION,
    all_datas,
)

icon = PACKAGE_DIR / "resources" / "icon.ico"

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
    # console=False: this is a GUI app, and a console window flashing up on launch looks
    # broken. Diagnostics go to the log file in the user data dir instead.
    console=False,
    disable_windowed_traceback=False,
    icon=str(icon) if icon.is_file() else None,
    version_info={"version": VERSION},
)

collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name=EXE_NAME,
)
