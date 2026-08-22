"""Application bootstrap: build everything once, in one place, in the right order.

The order matters and is not arbitrary:

1. graphics policy **before** ``QGuiApplication`` exists (Qt reads it at construction);
2. the asyncio worker loop, because the repository and the sources live on it;
3. storage, sources, services — the layers below the GUI, none of which know about Qt;
4. the bridge, which is the only object QML sees;
5. the QML engine, with the import path set so ``import Theme`` and ``import components``
   resolve identically in a dev checkout and inside a PyInstaller bundle.

This is also the one place allowed to hold a singleton (``AppContext``); everything else
receives what it needs.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from . import envs
from .core.logging import configure, get_logger
from .core.settings import AppPaths, AppSettings
from .gui.bridge import AppBridge
from .gui.tasks import AsyncRunner
from .gui.window import WindowEffects, configure_graphics
from .services.notifier import Notifier
from .services.scanner import Scanner
from .services.scheduler import Scheduler
from .sources import build_chain
from .storage.repository import Repository

log = get_logger("app")

# Where the QML lives, relative to this file. Resolved at import so a frozen build (where
# __file__ points inside the bundle) works with no special-casing.
QML_ROOT = Path(__file__).resolve().parent / "gui" / "qml"
MAIN_QML = QML_ROOT / "AppWindow.qml"

# The repo's bundled defaults, when running from a checkout. Absent in a wheel/bundle, which
# is fine — the model defaults are the same values.
BUNDLED_SETTINGS = Path(__file__).resolve().parents[2] / "config" / "settings.toml"


@dataclass
class AppContext:
    """Everything the app is made of, assembled once."""

    settings: AppSettings
    runner: AsyncRunner
    repository: Repository
    scanner: Scanner
    scheduler: Scheduler
    bridge: AppBridge
    effects: WindowEffects

    def shutdown(self) -> None:
        """Tear down in reverse order of construction, on the way out of ``main``."""
        try:
            self.runner.run_sync(lambda: self.scheduler.stop(), timeout=5.0)
        except Exception:
            log.debug("scheduler stop raised during shutdown", exc_info=True)
        try:
            self.runner.run_sync(lambda: self.scanner.chain.aclose(), timeout=5.0)
            self.runner.run_sync(lambda: self.repository.close(), timeout=5.0)
        except Exception:
            log.debug("resource close raised during shutdown", exc_info=True)
        self.runner.shutdown()


def load_settings(
    *, demo: bool = False, data_dir: Optional[Path] = None
) -> AppSettings:
    """Build the settings tree from every layer, applying CLI overrides last."""
    settings = AppSettings.load(
        bundled=BUNDLED_SETTINGS if BUNDLED_SETTINGS.is_file() else None,
        user=AppPaths.settings_file(),
    )
    if demo or envs.DEMO_MODE:
        settings.demo_mode = True
    if data_dir is not None:
        # Assigning through the model keeps validation in play (validate_assignment=True).
        AppPaths.data_dir = data_dir  # type: ignore[misc]
    return settings


def build_context(settings: AppSettings) -> AppContext:
    """Wire the layers together. No Qt widgets/windows are created here."""
    AppPaths.ensure()
    runner = AsyncRunner()

    repository = Repository(AppPaths.database_file())
    runner.run_sync(lambda: repository.open())

    chain = build_chain(settings)
    scanner = Scanner(settings, chain, repository)
    notifier = Notifier(enabled=settings.scan.notify_on_new_deal)

    if settings.demo_mode:
        from .services.demo import seed_demo

        runner.run_sync(lambda: seed_demo(repository, chain), timeout=30.0)

    bridge_holder: dict[str, AppBridge] = {}

    async def scheduled_scan() -> None:
        """What the scheduler runs. Routed through the bridge so the UI updates too."""
        bridge = bridge_holder.get("bridge")
        if bridge is not None:
            # request_scan, not scanNow: this coroutine runs on the asyncio worker thread,
            # and the bridge's Qt children must be created on the GUI thread (ADR-003).
            bridge.request_scan()

    scheduler = Scheduler(settings, scheduled_scan)
    bridge = AppBridge(
        settings, runner, scanner, repository, scheduler=scheduler, notifier=notifier
    )
    bridge_holder["bridge"] = bridge

    return AppContext(
        settings=settings,
        runner=runner,
        repository=repository,
        scanner=scanner,
        scheduler=scheduler,
        bridge=bridge,
        effects=WindowEffects(),
    )


def create_engine(context: AppContext) -> QQmlApplicationEngine:
    """Create the QML engine, expose the bridge, and load the shell.

    Raises:
        RuntimeError: The QML failed to produce a root object — almost always a syntax error
            or a missing import, which Qt reports on stderr and we must not swallow.
    """
    engine = QQmlApplicationEngine()
    # `qml/` itself is the import root: `import Theme` and `import components` then resolve
    # through the qmldir files, which is what makes the same imports work in a bundle.
    engine.addImportPath(str(QML_ROOT))

    # Named `appBridge`, not `bridge`: AppWindow declares `property var bridge: appBridge`,
    # and a context property of the same name would shadow the property rather than
    # initialise it. That shadowing is what left every view's Component.onCompleted looking
    # at a null bridge — the watch list rendered "No watches yet" over ten stored watches.
    engine.rootContext().setContextProperty("appBridge", context.bridge)
    engine.rootContext().setContextProperty("appWindowEffects", context.effects)

    warnings: list[str] = []

    def on_warnings(errors: list) -> None:  # type: ignore[type-arg]
        for error in errors:
            text = error.toString()
            warnings.append(text)
            log.warning("QML: %s", text)

    engine.warnings.connect(on_warnings)
    engine.load(QUrl.fromLocalFile(str(MAIN_QML)))

    if not engine.rootObjects():
        raise RuntimeError(f"QML failed to load: {MAIN_QML}")

    if envs.QML_STRICT and warnings:
        raise RuntimeError(
            f"{len(warnings)} QML warning(s) with SALEHUNTER_QML_STRICT set"
        )

    root = engine.rootObjects()[0]
    context.effects.apply(root, translucent=context.settings.ui.translucent_window)
    return engine


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point. Returns the process exit code."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="sale-hunter", description="Shopee sale-day deal hunter"
    )
    parser.add_argument(
        "--demo", action="store_true", help="use the offline demo catalogue"
    )
    parser.add_argument(
        "--data-dir", type=Path, default=None, help="override the data directory"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="debug logging")
    args = parser.parse_args(argv)

    AppPaths.ensure()
    configure(
        logging.DEBUG if (args.verbose or envs.VERBOSE) else logging.INFO,
        log_file=AppPaths.log_file(),
    )

    settings = load_settings(demo=args.demo, data_dir=args.data_dir)

    # Must precede QGuiApplication construction.
    configure_graphics()
    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("Sale Hunter")
    app.setOrganizationName("osirisQdt2810")
    # "Basic" explicitly: the default style is native per platform, and a macOS-styled
    # control next to our own components is exactly the inconsistency ADR-002 exists to stop.
    QQuickStyle.setStyle("Basic")

    icon_path = Path(__file__).resolve().parent / "resources" / "icon.png"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    context = build_context(settings)
    try:
        create_engine(context)
    except RuntimeError as exc:
        log.error("%s", exc)
        context.shutdown()
        return 1

    if settings.scan.auto_scan:
        context.runner.loop.call_soon_threadsafe(context.scheduler.start)

    app.aboutToQuit.connect(context.shutdown)
    # The CHAIN, not the configured order: demo mode replaces it, so a line reading
    # "sources=['affiliate', 'browser', 'web']" while the fixture source is answering is a log
    # line that will mislead someone at 2am.
    log.info(
        "Sale Hunter ready (demo=%s, sources=%s)",
        settings.demo_mode,
        " -> ".join(adapter.id for adapter in context.scanner.chain.adapters),
    )
    return app.exec()
