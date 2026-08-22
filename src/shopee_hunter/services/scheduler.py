"""The auto-scan loop: sleep as long as the sale calendar says, then scan.

Kept apart from ``Scanner`` because *when* to scan and *how* to scan fail differently. The
scheduler's only job is timing, and its rules are: never scan more often than
``core.sale_calendar`` recommends, always survive a failed scan, and stay instantly
cancellable so closing the window does not wait out a 6-hour sleep.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Optional

from ..core.logging import get_logger
from ..core.sale_calendar import SaleTier, current_tier, recommended_interval
from ..core.settings import AppSettings

# Sleep in slices so a cancel or a settings change is noticed in seconds, not hours. The
# alternative (one long `asyncio.sleep`) makes "auto-scan off" take effect after the nap.
_SLEEP_SLICE_SECONDS = 5.0

ScanCallable = Callable[[], Awaitable[object]]


class Scheduler:
    """Drives periodic scans at the cadence the sale calendar recommends."""

    def __init__(
        self,
        settings: AppSettings,
        run_scan: ScanCallable,
        *,
        on_tier_change: Optional[Callable[[SaleTier], None]] = None,
    ) -> None:
        self.settings = settings
        self.run_scan = run_scan
        self.on_tier_change = on_tier_change
        self.log = get_logger("services.scheduler")
        self._task: Optional[asyncio.Task[None]] = None
        self._wake = asyncio.Event()
        self._last_tier: Optional[SaleTier] = None
        self.next_scan_at: Optional[datetime] = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Begin the loop (no-op if already running)."""
        if self.running:
            return
        self._task = asyncio.create_task(self._loop(), name="sale-hunter-scheduler")
        self.log.info("auto-scan started")

    async def stop(self) -> None:
        """Cancel the loop and wait for it to unwind."""
        if self._task is None:
            return
        task, self._task = self._task, None
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self.log.info("auto-scan stopped")

    def scan_now(self) -> None:
        """Cut the current sleep short (the UI's "Scan now" button)."""
        self._wake.set()

    def interval_seconds(self, now: Optional[datetime] = None) -> float:
        """How long to wait before the next scan, honouring a user override."""
        override = self.settings.scan.interval_override_seconds
        if override:
            return float(max(60, override))
        return recommended_interval(now or datetime.now(UTC)).total_seconds()

    async def _loop(self) -> None:
        while True:
            now = datetime.now(UTC)
            tier = current_tier(now)
            if tier != self._last_tier:
                self._last_tier = tier
                if self.on_tier_change is not None:
                    self.on_tier_change(tier)
                self.log.info("sale tier is now %s", tier.name)

            try:
                await self.run_scan()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.log.exception("scheduled scan failed; continuing")

            await self._sleep(self.interval_seconds())

    async def _sleep(self, seconds: float) -> None:
        """Sleep in slices, waking early on ``scan_now()``."""
        self.next_scan_at = datetime.fromtimestamp(
            datetime.now(UTC).timestamp() + seconds, tz=UTC
        )
        remaining = seconds
        while remaining > 0:
            slice_seconds = min(_SLEEP_SLICE_SECONDS, remaining)
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=slice_seconds)
            except TimeoutError:
                remaining -= slice_seconds
                continue
            self._wake.clear()
            self.log.debug("woken early")
            return
