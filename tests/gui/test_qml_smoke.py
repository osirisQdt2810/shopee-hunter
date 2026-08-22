"""QML smoke loads: every component and view must load with zero warnings.

QML fails at *runtime*, silently — a mistyped Theme token or a missing qmldir entry renders an
empty panel rather than raising. These tests are the reason that cannot reach a user: they
load each file in isolation and treat any engine warning as a failure (ADR-002).

Marked ``gui``; CI runs them with ``QT_QPA_PLATFORM=offscreen``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.gui

QML_ROOT = Path(__file__).resolve().parents[2] / "src" / "shopee_hunter" / "gui" / "qml"

# Components that need a live bridge or a Window parent are loaded through AppWindow instead.
STANDALONE_SKIP = {"AppWindow.qml", "Theme.qml", "TitleBar.qml"}


def _qml_files() -> list[Path]:
    return sorted(
        path for path in QML_ROOT.rglob("*.qml") if path.name not in STANDALONE_SKIP
    )


@pytest.fixture
def engine(qapp):
    """A QML engine with the project's import path, collecting every warning."""
    from PySide6.QtQml import QQmlEngine
    from PySide6.QtQuickControls2 import QQuickStyle

    QQuickStyle.setStyle("Basic")
    engine = QQmlEngine()
    engine.addImportPath(str(QML_ROOT))
    warnings: list[str] = []
    engine.warnings.connect(
        lambda errors: warnings.extend(e.toString() for e in errors)
    )
    engine.warnings_seen = warnings  # type: ignore[attr-defined]
    return engine


def test_the_theme_singleton_loads(engine):
    """Everything else depends on it, so it gets its own test with a clearer failure."""
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent

    component = QQmlComponent(
        engine, QUrl.fromLocalFile(str(QML_ROOT / "Theme" / "Theme.qml"))
    )
    theme = component.create()

    assert component.isReady(), component.errorString()
    assert theme is not None
    # A couple of tokens every component reads, so a rename fails here rather than everywhere.
    assert theme.property("radiusLg") is not None
    assert theme.property("fontFamily")


@pytest.mark.parametrize(
    "path", _qml_files(), ids=lambda p: f"{p.parent.name}/{p.name}"
)
def test_component_loads_without_warnings(engine, path: Path):
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent

    component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
    instance = component.create()

    assert (
        component.isReady()
    ), f"{path.name} failed to compile:\n{component.errorString()}"
    assert instance is not None, f"{path.name} compiled but produced no object"
    assert (
        not engine.warnings_seen
    ), f"{path.name} emitted QML warnings: {engine.warnings_seen}"


def test_the_whole_shell_loads_with_a_real_bridge(qapp, tmp_path, monkeypatch):
    """The one integration load: AppWindow with the bridge QML actually binds to."""
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle

    monkeypatch.setenv("SALEHUNTER_DEMO_MODE", "true")
    from shopee_hunter.app import MAIN_QML, build_context, load_settings
    from shopee_hunter.core.settings import AppPaths

    monkeypatch.setattr(AppPaths, "data_dir", tmp_path)
    monkeypatch.setattr(AppPaths, "config_dir", tmp_path)
    monkeypatch.setattr(AppPaths, "cache_dir", tmp_path)
    monkeypatch.setattr(AppPaths, "log_dir", tmp_path)

    QQuickStyle.setStyle("Basic")
    context = build_context(load_settings(demo=True))
    try:
        engine = QQmlApplicationEngine()
        engine.addImportPath(str(QML_ROOT))
        engine.rootContext().setContextProperty("appBridge", context.bridge)
        engine.rootContext().setContextProperty("appWindowEffects", context.effects)
        warnings: list[str] = []
        engine.warnings.connect(
            lambda errors: warnings.extend(e.toString() for e in errors)
        )
        engine.load(QUrl.fromLocalFile(str(MAIN_QML)))

        assert engine.rootObjects(), f"AppWindow produced no root object: {warnings}"
        assert not warnings, f"AppWindow emitted QML warnings: {warnings}"

        window = engine.rootObjects()[0]
        # The bridge binding is the thing that broke once (a same-named context property
        # shadowed the declared property, leaving every view with a null bridge).
        assert window.property("bridge") is not None, "AppWindow.bridge did not bind"
    finally:
        context.shutdown()
