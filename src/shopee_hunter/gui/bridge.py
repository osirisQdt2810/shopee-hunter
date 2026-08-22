"""The QML-facing object. Slots in, signals out, no business logic.

Everything QML can do to the app, it does through here — and everything here delegates
immediately to a service. The bridge's own job is only translation: Qt types and camelCase
in, domain calls out; domain results back, formatted strings and signals out (ADR-002/003).

If a method in this file ever contains a price comparison or a discount threshold, it is in
the wrong layer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Optional

from PySide6.QtCore import Property, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from ..core.errors import SaleHunterError, SourceBlocked
from ..core.logging import get_logger
from ..core.models import Money, Watch
from ..core.sale_calendar import (
    SaleTier,
    current_tier,
    is_elevated,
    is_peak,
    next_window,
)
from ..core.settings import AppSettings
from ..services.notifier import Notifier
from ..services.scanner import Scanner, ScanResult
from ..services.scheduler import Scheduler
from ..storage.repository import Repository
from .models import DealListModel, WatchListModel, format_money
from .tasks import AsyncRunner

log = get_logger("gui.bridge")

# Toast severities QML styles differently. Strings, not an enum, because QML reads them.
TOAST_INFO = "info"
TOAST_WARN = "warn"
TOAST_ERROR = "error"

_TIER_LABEL = {
    SaleTier.QUIET: "No sale running",
    SaleTier.FLASH_SLOT: "Flash sale slot open",
    SaleTier.PAYDAY: "Payday sale",
    SaleTier.DOUBLE_DATE: "Double-date sale",
    SaleTier.MEGA: "MEGA SALE",
}


def tone_for_tier(tier: SaleTier) -> str:
    """Map a sale tier onto one of the `Badge` component's tone names.

    A module-level function rather than logic inside the property, so it is reachable by a
    test without standing up a whole `AppBridge` — an untestable mapping is how the
    `tierLevel >= 3` version survived in QML in the first place.

    The *classification* (which tiers are campaigns) belongs to `core.sale_calendar`; only
    the choice of colour vocabulary is made here, which is presentation and so may live in
    `gui/`.
    """
    if is_peak(tier):
        return "accent"
    return "caution" if is_elevated(tier) else "neutral"


class AppBridge(QObject):
    """Single QML context object: state as properties, actions as slots."""

    # -- notifications to QML ---------------------------------------------------
    # _scanRequested is INTERNAL, not for QML: the scheduler lives on the asyncio thread
    # and must not call a slot on this object directly. Emitting a signal is thread-safe,
    # and Qt delivers it as a queued call on the GUI thread — which is where the AsyncTask
    # children have to be created. Calling scanNow() from the worker thread produced
    # "Cannot create children for a parent that is in a different thread" on the very
    # first scheduled scan.
    _scanRequested = Signal()

    busyChanged = Signal()
    statusChanged = Signal()
    saleStateChanged = Signal()
    scanStarted = Signal()
    scanProgress = Signal(int, int, str)
    scanFinished = Signal(int, str)
    toast = Signal(str, str)  # message, severity

    def __init__(
        self,
        settings: AppSettings,
        runner: AsyncRunner,
        scanner: Scanner,
        repository: Repository,
        *,
        scheduler: Optional[Scheduler] = None,
        notifier: Optional[Notifier] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._runner = runner
        self._scanner = scanner
        self._repository = repository
        self._scheduler = scheduler
        self._notifier = notifier or Notifier(enabled=settings.scan.notify_on_new_deal)

        self._deals = DealListModel(self)
        self._watches = WatchListModel(self)
        self._busy = False
        self._status = "Ready"
        self._source_used = ""
        self._last_scan: Optional[datetime] = None
        self._current_task: Optional[object] = None

        # Queued explicitly rather than relying on Qt's automatic connection type: the
        # guarantee needed is "always run on the bridge's own thread", and automatic mode
        # runs it directly whenever the emitter happens to share that thread.
        self._scanRequested.connect(self.scanNow, Qt.ConnectionType.QueuedConnection)

    # -- models QML binds to ----------------------------------------------------
    @Property(QObject, constant=True)
    def deals(self) -> DealListModel:
        return self._deals

    @Property(QObject, constant=True)
    def watches(self) -> WatchListModel:
        return self._watches

    # -- scalar state -----------------------------------------------------------
    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(str, notify=statusChanged)
    def sourceUsed(self) -> str:
        return self._source_used

    @Property(int, notify=statusChanged)
    def dealCount(self) -> int:
        """Every deal on the list, verified or not."""
        return self._deals.rowCount()

    @Property(int, notify=statusChanged)
    def genuineCount(self) -> int:
        """Only the deals the engine verified — what a tile labelled "verified" must show."""
        return self._deals.genuine_count()

    @Property(str, notify=statusChanged)
    def lastScanText(self) -> str:
        if self._last_scan is None:
            return "never"
        seconds = (datetime.now(UTC) - self._last_scan).total_seconds()
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            return f"{int(seconds // 60)} min ago"
        return f"{int(seconds // 3600)} h ago"

    @Property(str, notify=saleStateChanged)
    def tierName(self) -> str:
        return current_tier(datetime.now(UTC)).name

    @Property(str, notify=saleStateChanged)
    def tierLabel(self) -> str:
        return _TIER_LABEL[current_tier(datetime.now(UTC))]

    @Property(int, notify=saleStateChanged)
    def tierLevel(self) -> int:
        """0–4, for scaling a *continuous* visual intensity (see `Theme.tierGlow`).

        Do not branch on it. A ramp over the ordinal degrades gracefully when a tier is
        inserted — the glow shifts a little — whereas `tierLevel >= 3` silently changes which
        days count as loud. Anything categorical belongs on `tierIsPeak` or `tierTone`.
        """
        return int(current_tier(datetime.now(UTC)))

    @Property(bool, notify=saleStateChanged)
    def tierIsPeak(self) -> bool:
        """Is a big campaign window running right now? Drives the header's emphasis."""
        return is_peak(current_tier(datetime.now(UTC)))

    @Property(str, notify=saleStateChanged)
    def tierTone(self) -> str:
        """The badge tone for the current tier, as a name the Badge component understands."""
        return tone_for_tier(current_tier(datetime.now(UTC)))

    @Property(str, notify=saleStateChanged)
    def nextSaleText(self) -> str:
        """ "12.12 Mega Sale in 3d 04h" — the countdown in the header."""
        now = datetime.now(UTC)
        window = next_window(now, min_tier=SaleTier.DOUBLE_DATE)
        if window is None:
            return ""
        remaining = window.starts_in(now)
        days, seconds = remaining.days, remaining.seconds
        if days > 0:
            return f"{window.name} in {days}d {seconds // 3600:02d}h"
        return f"{window.name} in {seconds // 3600:02d}h {(seconds % 3600) // 60:02d}m"

    @Property(str, constant=True)
    def accent(self) -> str:
        return self._settings.ui.accent

    @Property(bool, constant=True)
    def reducedMotion(self) -> bool:
        return self._settings.ui.reduced_motion

    @Property(float, constant=True)
    def animationScale(self) -> float:
        return self._settings.ui.animation_scale

    @Property(bool, constant=True)
    def demoMode(self) -> bool:
        return self._settings.demo_mode

    @Property(str, constant=True)
    def storefront(self) -> str:
        return self._settings.storefront.domain

    # -- actions ----------------------------------------------------------------
    def request_scan(self) -> None:
        """Ask for a scan from ANY thread — the only safe entry point off the GUI thread.

        Used by the scheduler, which runs on the asyncio worker loop. Everything else
        (QML, signal handlers) is already on the GUI thread and calls ``scanNow`` directly.
        """
        self._scanRequested.emit()

    @Slot()
    def scanNow(self) -> None:
        """Scan every enabled watch. Ignored while a scan is already running."""
        if self._busy:
            self.toast.emit("A scan is already running", TOAST_INFO)
            return
        self._start_scan(self._scan_watches_coro)

    @Slot(str, int, float)
    def searchKeyword(self, keyword: str, max_price: int, min_discount: float) -> None:
        """Ad-hoc search from the UI's search box.

        ``max_price`` of 0 and ``min_discount`` of 0 both mean "no limit" — QML has no null
        for a number, so 0 is the sentinel, documented here rather than guessed at each site.
        """
        keyword = keyword.strip()
        if not keyword:
            self.toast.emit("Type something to search for", TOAST_INFO)
            return
        if self._busy:
            self.toast.emit("A scan is already running", TOAST_INFO)
            return

        async def coro() -> ScanResult:
            return await self._scanner.scan_keyword(
                keyword,
                max_price=max_price or None,
                min_discount_pct=min_discount or None,
            )

        self._start_scan(lambda: coro())

    @Slot()
    def scanFlashSale(self) -> None:
        """Scan the current flash-sale batch — the best value during a slot."""
        if self._busy:
            return
        self._start_scan(lambda: self._scanner.flash_sale())

    @Slot()
    def cancelScan(self) -> None:
        if self._current_task is not None and self._current_task.running:
            self._current_task.cancel()
            self._set_status("Cancelling…")

    @Slot(str, int, float, float, str, bool)
    def addWatch(
        self,
        keyword: str,
        max_price: int,
        min_discount: float,
        min_rating: float,
        exclude_terms: str,
        official_only: bool,
    ) -> None:
        """Create a watch from the QML form. Validation errors come back as a toast."""
        keyword = keyword.strip()
        if not keyword:
            self.toast.emit("A watch needs a keyword", TOAST_WARN)
            return
        watch = Watch(
            watch_id=f"w-{uuid.uuid4().hex[:8]}",
            keyword=keyword,
            max_price=Money(max_price) if max_price > 0 else None,
            min_discount_pct=max(0.0, min_discount),
            min_rating=min_rating if min_rating > 0 else None,
            exclude_terms=tuple(
                term.strip()
                for term in exclude_terms.replace(";", ",").split(",")
                if term.strip()
            ),
            official_only=official_only,
        )

        async def coro() -> None:
            await self._repository.save_watch(watch)

        task = self._runner.submit(lambda: coro(), parent=self)
        task.finished.connect(
            lambda _: self._after_watch_change(f"Watching “{keyword}”")
        )
        task.failed.connect(self._on_error)

    @Slot(str)
    def removeWatch(self, watch_id: str) -> None:
        async def coro() -> bool:
            return await self._repository.delete_watch(watch_id)

        task = self._runner.submit(lambda: coro(), parent=self)
        task.finished.connect(lambda _: self._after_watch_change("Watch removed"))
        task.failed.connect(self._on_error)

    @Slot(str, bool)
    def setWatchEnabled(self, watch_id: str, enabled: bool) -> None:
        from dataclasses import replace

        row = next(
            (
                i
                for i in range(self._watches.rowCount())
                if (w := self._watches.watch_at(i)) and w.watch_id == watch_id
            ),
            None,
        )
        watch = self._watches.watch_at(row) if row is not None else None
        if watch is None:
            return

        async def coro() -> None:
            await self._repository.save_watch(replace(watch, enabled=enabled))

        task = self._runner.submit(lambda: coro(), parent=self)
        task.finished.connect(lambda _: self._after_watch_change(""))
        task.failed.connect(self._on_error)

    @Slot()
    def refreshWatches(self) -> None:
        task = self._runner.submit(lambda: self._repository.list_watches(), parent=self)
        task.finished.connect(self._watches.set_watches)
        task.failed.connect(self._on_error)

    @Slot(str)
    def openUrl(self, url: str) -> None:
        """Open a listing in the user's browser.

        Guarded to http(s): a URL string reaching here came from a parsed response, and
        handing an arbitrary scheme to the OS opener is how a data source becomes an
        execution vector.
        """
        parsed = QUrl(url)
        if parsed.scheme() not in ("http", "https"):
            log.warning("refusing to open non-http url: %s", url)
            self.toast.emit("Refused to open a non-web link", TOAST_WARN)
            return
        QDesktopServices.openUrl(parsed)

    @Slot(bool)
    def setAutoScan(self, enabled: bool) -> None:
        if self._scheduler is None:
            return
        if enabled:
            self._runner.loop.call_soon_threadsafe(self._scheduler.start)
            self.toast.emit(
                "Auto-scan on — cadence follows the sale calendar", TOAST_INFO
            )
        else:
            self._runner.submit(lambda: self._scheduler.stop(), parent=self)
            self.toast.emit("Auto-scan off", TOAST_INFO)

    # -- internals --------------------------------------------------------------
    async def _scan_watches_coro(self) -> ScanResult:
        watches = await self._repository.list_watches(enabled_only=True)
        return await self._scanner.scan_watches(
            watches,
            progress=lambda done, total, label: self.scanProgress.emit(
                done, total, label
            ),
        )

    def _start_scan(self, factory) -> None:  # type: ignore[no-untyped-def]
        self._set_busy(True)
        self._set_status("Scanning…")
        self.scanStarted.emit()
        task = self._runner.submit(factory, parent=self)
        task.finished.connect(self._on_scan_finished)
        task.failed.connect(self._on_error)
        task.cancelled.connect(self._on_cancelled)
        self._current_task = task

    def _on_scan_finished(self, result: object) -> None:
        if not isinstance(result, ScanResult):
            self._set_busy(False)
            return

        history_task = self._runner.submit(
            lambda: self._repository.history_for_many(
                [(d.product.item_id, d.product.shop_id) for d in result.deals],
                lookback_days=self._settings.scan.history_lookback_days,
            ),
            parent=self,
        )
        history_task.finished.connect(
            lambda history: self._apply_result(
                result, history if isinstance(history, dict) else {}
            )
        )
        history_task.failed.connect(lambda _: self._apply_result(result, {}))

    def _apply_result(self, result: ScanResult, history: dict) -> None:
        self._deals.set_deals(result.deals, history)
        self._last_scan = datetime.now(UTC)
        self._source_used = result.source_used or ""
        self._set_busy(False)

        if result.blocked:
            self._set_status("Shopee is refusing requests — backing off")
            self.toast.emit(
                "Shopee blocked the request. Try the browser source, or wait a few minutes.",
                TOAST_WARN,
            )
        else:
            self._set_status(result.summary())
            if result.errors:
                self.toast.emit(f"Partial scan: {result.errors[0]}", TOAST_WARN)

        self.scanFinished.emit(len(result.deals), result.summary())
        self.saleStateChanged.emit()
        self._notify(result)

    def _notify(self, result: ScanResult) -> None:
        async def coro() -> int:
            fresh = await self._scanner.notifiable(result)
            return await self._notifier.notify_deals(fresh)

        self._runner.submit(lambda: coro(), parent=self)

    def _after_watch_change(self, message: str) -> None:
        self.refreshWatches()
        if message:
            self.toast.emit(message, TOAST_INFO)

    def _on_cancelled(self) -> None:
        self._set_busy(False)
        self._set_status("Scan cancelled")
        self.toast.emit("Scan cancelled", TOAST_INFO)

    def _on_error(self, error: object) -> None:
        self._set_busy(False)
        if isinstance(error, SourceBlocked):
            self._set_status("Shopee is refusing requests")
            self.toast.emit(str(error), TOAST_WARN)
            return
        message = (
            str(error)
            if isinstance(error, SaleHunterError)
            else f"Unexpected error: {error}"
        )
        log.error(
            "bridge error: %s", message, exc_info=isinstance(error, BaseException)
        )
        self._set_status("Error")
        self.toast.emit(message, TOAST_ERROR)

    def _set_busy(self, value: bool) -> None:
        if self._busy != value:
            self._busy = value
            self.busyChanged.emit()

    def _set_status(self, text: str) -> None:
        self._status = text
        self.statusChanged.emit()

    @Slot(int, result=str)
    def formatMoney(self, amount: int) -> str:
        """Money formatting for QML forms — one implementation, not one per delegate."""
        return format_money(Money(amount))
