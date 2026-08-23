#!/usr/bin/env python3
"""Launch the real app, screenshot every view, exit.

This is half of the live tier (ADR-008). A `pytest-qt` smoke test proves a QML file *loads*;
only a rendered pixel proves it looks like anything. So this drives the actual window through
each view and writes PNGs a human — or a PR reviewer — can look at.

    python scripts/ui_screenshot.py --out .artifacts/ui
    python scripts/ui_screenshot.py --out .artifacts/ui --offscreen   # CI-safe, software renderer

Exit code: 0 all views captured, 1 something failed (a QML warning counts as a failure).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

# Views in navigation order — the index is what AppWindow's `currentView` takes.
VIEWS: tuple[tuple[int, str], ...] = (
    (0, "deals"),
    (1, "watches"),
    (2, "calendar"),
    (3, "how-it-works"),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / ".artifacts" / "ui")
    parser.add_argument(
        "--offscreen",
        action="store_true",
        help="render headless with the software backend (what CI uses)",
    )
    parser.add_argument(
        "--settle-ms",
        type=int,
        default=1400,
        help="wait per view before grabbing, so entrance animations finish",
    )
    parser.add_argument(
        "--live", action="store_true", help="use real sources instead of demo data"
    )
    args = parser.parse_args(argv)

    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    if not args.live:
        # Demo data by default: deterministic pixels are what make these diffable, and a
        # screenshot run should not depend on Shopee being in a good mood.
        os.environ["SALEHUNTER_DEMO_MODE"] = "true"
    os.environ.setdefault(
        "SALEHUNTER_DATA_DIR", str(REPO_ROOT / ".artifacts" / "screenshot-data")
    )

    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle

    from shopee_hunter.app import MAIN_QML, QML_ROOT, build_context, load_settings
    from shopee_hunter.gui.window import configure_graphics

    configure_graphics()
    # Bound to a name deliberately: an unreferenced QGuiApplication can be collected while
    # the QML engine still needs it, and the failure looks like a rendering bug.
    _app = QGuiApplication(sys.argv[:1])
    assert _app is not None
    QQuickStyle.setStyle("Basic")

    settings = load_settings(demo=not args.live)
    context = build_context(settings)

    engine = QQmlApplicationEngine()
    engine.addImportPath(str(QML_ROOT))
    engine.rootContext().setContextProperty("appBridge", context.bridge)
    engine.rootContext().setContextProperty("appWindowEffects", context.effects)

    warnings: list[str] = []
    engine.warnings.connect(
        lambda errors: warnings.extend(e.toString() for e in errors)
    )
    engine.load(QUrl.fromLocalFile(str(MAIN_QML)))

    roots = engine.rootObjects()
    if not roots:
        print("FAIL: QML produced no root object", file=sys.stderr)
        for warning in warnings:
            print(f"  {warning}", file=sys.stderr)
        context.shutdown()
        return 1

    window = roots[0]
    context.effects.apply(window, translucent=settings.ui.translucent_window)

    args.out.mkdir(parents=True, exist_ok=True)

    def settle(milliseconds: int) -> None:
        """Pump the event loop so animations advance and the scene graph repaints."""
        loop = QEventLoop()
        QTimer.singleShot(milliseconds, loop.quit)
        loop.exec()

    # Populate the deal list first: an empty-state screenshot of every view proves nothing.
    context.bridge.scanNow()
    settle(2600)

    written: list[Path] = []
    for index, name in VIEWS:
        window.setProperty("currentView", index)
        settle(args.settle_ms)
        image = window.grabWindow()
        if image.isNull():
            print(
                f"FAIL: grabWindow() returned a null image for {name}", file=sys.stderr
            )
            context.shutdown()
            return 1
        target = args.out / f"{index:02d}-{name}.png"
        if not image.save(str(target)):
            print(f"FAIL: could not write {target}", file=sys.stderr)
            context.shutdown()
            return 1
        written.append(target)
        print(f"  {target}  ({image.width()}x{image.height()})")

    print(f"\n{len(written)} screenshot(s) written to {args.out}")
    print(
        f"deals rendered: {context.bridge.deals.rowCount()}  |  status: {context.bridge.status}"
    )

    if warnings:
        print(
            f"\n{len(warnings)} QML warning(s) — a warning is a defect, not noise:",
            file=sys.stderr,
        )
        for warning in dict.fromkeys(warnings):
            print(f"  {warning}", file=sys.stderr)

    context.shutdown()
    return 1 if warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
