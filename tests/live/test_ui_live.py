"""LIVE UI test: build the real window and render it.

A ``pytest-qt`` smoke test proves the QML *loads*. This proves it renders — the scene graph
produces pixels on a real GPU, which is where "loads fine, shows nothing" hides (ADR-002).

Run with ``pytest -m live``. Uses demo data so it does not depend on Shopee's mood.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.live


@pytest.fixture
def rendered_window(tmp_path):
    """The real AppWindow, with the real bridge, wound forward past its animations."""
    os.environ["SALEHUNTER_DEMO_MODE"] = "true"
    os.environ["SALEHUNTER_DATA_DIR"] = str(tmp_path)

    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle

    from shopee_hunter.app import MAIN_QML, QML_ROOT, build_context, load_settings
    from shopee_hunter.gui.window import configure_graphics

    configure_graphics()
    # Kept in a name: the QGuiApplication must outlive this fixture's setup, and an
    # unreferenced one can be collected out from under the engine.
    _app = QGuiApplication.instance() or QGuiApplication([])
    assert _app is not None
    QQuickStyle.setStyle("Basic")

    context = build_context(load_settings(demo=True))
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(QML_ROOT))
    engine.rootContext().setContextProperty("appBridge", context.bridge)
    engine.rootContext().setContextProperty("appWindowEffects", context.effects)

    warnings: list[str] = []
    engine.warnings.connect(
        lambda errors: warnings.extend(e.toString() for e in errors)
    )
    engine.load(QUrl.fromLocalFile(str(MAIN_QML)))

    def settle(ms: int) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    roots = engine.rootObjects()
    assert roots, f"QML produced no root object: {warnings}"
    context.bridge.scanNow()
    settle(2500)

    yield roots[0], context, warnings, settle

    context.shutdown()


class TestRealWindow:
    def test_the_window_renders_pixels(self, rendered_window):
        window, _context, warnings, _settle = rendered_window

        image = window.grabWindow()

        assert (
            not image.isNull()
        ), "grabWindow() produced nothing — the scene graph is not drawing"
        assert image.width() > 0 and image.height() > 0
        assert not warnings, f"QML warnings are defects, not noise: {warnings}"

    def test_the_deal_list_actually_populated(self, rendered_window):
        _window, context, _warnings, _settle = rendered_window

        assert context.bridge.deals.rowCount() > 0, (
            "the demo catalogue produced no deals — the engine, the demo seed, or the bridge "
            "wiring is broken"
        )

    def test_every_view_renders(self, rendered_window):
        window, _context, warnings, settle = rendered_window

        for index in range(4):
            window.setProperty("currentView", index)
            settle(700)
            image = window.grabWindow()
            assert not image.isNull(), f"view {index} rendered nothing"

        assert not warnings, f"switching views produced QML warnings: {warnings}"

    def test_the_rendered_frame_is_not_a_flat_colour(self, rendered_window):
        """A window that paints one colour is a window that failed to compose.

        Cheap check, real bug: a missing scene-graph backend, a failed effect, or an
        unbound model all show up as a uniform rectangle rather than as an error.
        """
        window, _context, _warnings, _settle = rendered_window

        image = window.grabWindow().toImage()
        step = max(1, image.width() // 40)
        colours = {
            image.pixel(x, y)
            for x in range(0, image.width(), step)
            for y in range(0, image.height(), step)
        }

        assert (
            len(colours) > 20
        ), f"only {len(colours)} distinct colours — the window is blank"
