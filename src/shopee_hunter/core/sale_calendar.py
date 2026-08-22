"""When Shopee actually discounts things.

Scanning at a flat interval wastes requests for 27 days and then misses the 3 minutes that
matter. Shopee's Vietnamese storefront runs on a very regular rhythm, so the app can be
lazy most of the time and aggressive exactly when prices move:

* **double-date** campaigns — the day equals the month (1.1, 2.2, … 12.12);
* **mega** campaigns — the same rule for 9.9, 11.11 and 12.12, which are far bigger;
* **payday** sales — the 15th and the 25th, when Vietnamese salaries land;
* **flash-sale slots** — fixed times every single day.

Everything here is a pure function of an explicit ``now``: no module-level clock, so the
tests can sit on 12.12 without waiting for December.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from enum import IntEnum
from typing import Optional

# Shopee VN's flash-sale slots (local storefront time). Prices change *at* these times, so
# a scan is worth far more just after one opens than 40 minutes into it.
FLASH_SALE_HOURS: tuple[int, ...] = (0, 9, 12, 15, 18, 21)

# The storefront's timezone. Sale days are calendar days in Vietnam, not in UTC — running
# the app from another timezone must not shift 12.12 by a day.
STOREFRONT_UTC_OFFSET = timedelta(hours=7)
STOREFRONT_TZ = timezone(STOREFRONT_UTC_OFFSET, name="ICT")

MEGA_DAYS: frozenset[tuple[int, int]] = frozenset({(9, 9), (11, 11), (12, 12)})
PAYDAY_DAYS: frozenset[int] = frozenset({15, 25})


class SaleTier(IntEnum):
    """How hard to scan. Higher tier = shorter interval, more pages, more watches."""

    QUIET = 0
    FLASH_SLOT = 1
    PAYDAY = 2
    DOUBLE_DATE = 3
    MEGA = 4


# Recommended seconds between scans per tier. Conservative on purpose: the token bucket in
# ``core.rate_limit`` is the hard ceiling, this is the polite cadence underneath it.
SCAN_INTERVAL_SECONDS: dict[SaleTier, int] = {
    SaleTier.QUIET: 60 * 60 * 6,
    SaleTier.FLASH_SLOT: 60 * 10,
    SaleTier.PAYDAY: 60 * 30,
    SaleTier.DOUBLE_DATE: 60 * 15,
    SaleTier.MEGA: 60 * 5,
}


@dataclass(frozen=True, slots=True, order=True)
class SaleWindow:
    """A period when discounts are expected, in UTC.

    Ordered by ``start`` so a list of windows sorts chronologically for the UI's countdown.
    """

    start: datetime
    end: datetime
    tier: SaleTier
    name: str

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end

    def starts_in(self, moment: datetime) -> timedelta:
        """Time until this window opens (negative once it has)."""
        return self.start - moment

    @property
    def duration(self) -> timedelta:
        return self.end - self.start


def _as_storefront(moment: datetime) -> datetime:
    """Interpret an instant in the storefront's timezone (naive input assumed UTC)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(STOREFRONT_TZ)


def _window(
    day: date, start_hour: int, hours: int, tier: SaleTier, name: str
) -> SaleWindow:
    """Build a UTC window from a storefront-local day and hour."""
    start_local = datetime.combine(day, time(hour=start_hour), tzinfo=STOREFRONT_TZ)
    return SaleWindow(
        start=start_local.astimezone(UTC),
        end=(start_local + timedelta(hours=hours)).astimezone(UTC),
        tier=tier,
        name=name,
    )


def classify_day(day: date) -> tuple[SaleTier, str]:
    """The campaign tier of a whole storefront day, and its name.

    Returns ``(SaleTier.QUIET, "")`` for an ordinary day — flash slots are handled
    separately because they exist on every day, quiet ones included.
    """
    if (day.month, day.day) in MEGA_DAYS:
        return SaleTier.MEGA, f"{day.day}.{day.month} Mega Sale"
    if day.day == day.month:
        return SaleTier.DOUBLE_DATE, f"{day.day}.{day.month} Sale"
    if day.day in PAYDAY_DAYS:
        return SaleTier.PAYDAY, f"Payday Sale {day.day}"
    if day.day == calendar.monthrange(day.year, day.month)[1]:
        return SaleTier.PAYDAY, "Month-end Sale"
    return SaleTier.QUIET, ""


def day_windows(day: date) -> list[SaleWindow]:
    """Every window on one storefront day: the campaign (if any) plus its flash slots.

    A flash slot is modelled as a 1-hour window because that is roughly how long a Shopee
    flash-sale batch keeps its price before the next batch rotates in.
    """
    windows: list[SaleWindow] = []
    tier, name = classify_day(day)
    if tier is not SaleTier.QUIET:
        windows.append(_window(day, 0, 24, tier, name))
    for hour in FLASH_SALE_HOURS:
        windows.append(
            _window(day, hour, 1, SaleTier.FLASH_SLOT, f"Flash Sale {hour:02d}:00")
        )
    return sorted(windows)


def iter_windows(start: datetime, days: int) -> Iterator[SaleWindow]:
    """Yield every window from ``start`` over the next ``days`` storefront days."""
    first = _as_storefront(start).date()
    for offset in range(max(days, 1)):
        yield from day_windows(first + timedelta(days=offset))


def active_windows(moment: datetime) -> list[SaleWindow]:
    """Windows open right now, strongest tier first.

    Overlap is normal and meaningful: 12.12 at 21:00 is a mega day *and* a flash slot.
    """
    now_utc = moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)
    local_day = _as_storefront(now_utc).date()
    candidates = day_windows(local_day - timedelta(days=1)) + day_windows(local_day)
    return sorted(
        (window for window in candidates if window.contains(now_utc)),
        key=lambda window: -window.tier,
    )


def current_tier(moment: datetime) -> SaleTier:
    """The strongest tier currently open (``QUIET`` when nothing is)."""
    windows = active_windows(moment)
    return windows[0].tier if windows else SaleTier.QUIET


def next_window(
    moment: datetime,
    *,
    min_tier: SaleTier = SaleTier.FLASH_SLOT,
    horizon_days: int = 400,
) -> Optional[SaleWindow]:
    """The next window at or above ``min_tier`` that has not started yet.

    ``horizon_days`` defaults past a year so "when is the next mega sale?" always answers.
    """
    now_utc = moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)
    for window in iter_windows(now_utc, horizon_days):
        if window.tier >= min_tier and window.start > now_utc:
            return window
    return None


def recommended_interval(moment: datetime) -> timedelta:
    """How long to wait before the next scan, given what is open.

    Also tightens *ahead* of a big campaign: within an hour of a mega/double-date window
    opening we switch to that window's cadence so the first minutes are covered.
    """
    tier = current_tier(moment)
    upcoming = next_window(moment, min_tier=SaleTier.DOUBLE_DATE, horizon_days=2)
    if upcoming is not None and upcoming.starts_in(moment) <= timedelta(hours=1):
        tier = max(tier, upcoming.tier)
    return timedelta(seconds=SCAN_INTERVAL_SECONDS[tier])
