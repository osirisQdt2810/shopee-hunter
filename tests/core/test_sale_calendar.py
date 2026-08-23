"""The sale calendar. Every case pins a date, because "it worked in December" is not a test."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from shopee_hunter.core.sale_calendar import (
    FLASH_SALE_HOURS,
    PEAK_TIERS,
    SCAN_INTERVAL_SECONDS,
    STOREFRONT_TZ,
    SaleTier,
    active_windows,
    classify_day,
    current_tier,
    day_windows,
    is_elevated,
    is_peak,
    next_window,
    recommended_interval,
)


def ict(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    """A storefront-local instant, returned in UTC — the app's internal convention."""
    return datetime(year, month, day, hour, minute, tzinfo=STOREFRONT_TZ).astimezone(
        UTC
    )


class TestClassifyDay:
    @pytest.mark.parametrize(
        ("day", "tier"),
        [
            (date(2026, 12, 12), SaleTier.MEGA),
            (date(2026, 11, 11), SaleTier.MEGA),
            (date(2026, 9, 9), SaleTier.MEGA),
            (date(2026, 3, 3), SaleTier.DOUBLE_DATE),
            (date(2026, 10, 10), SaleTier.DOUBLE_DATE),
            (date(2026, 5, 15), SaleTier.PAYDAY),
            (date(2026, 5, 25), SaleTier.PAYDAY),
            (date(2026, 5, 31), SaleTier.PAYDAY),
            (date(2026, 5, 20), SaleTier.QUIET),
        ],
    )
    def test_tiers(self, day: date, tier: SaleTier) -> None:
        assert classify_day(day)[0] is tier

    def test_february_end_is_a_payday_even_in_a_leap_year(self) -> None:
        assert classify_day(date(2028, 2, 29))[0] is SaleTier.PAYDAY

    def test_the_campaign_name_is_human_readable(self) -> None:
        assert classify_day(date(2026, 12, 12))[1] == "12.12 Mega Sale"


class TestWindows:
    def test_a_quiet_day_still_has_its_flash_slots(self) -> None:
        windows = day_windows(date(2026, 5, 20))

        assert len(windows) == len(FLASH_SALE_HOURS)
        assert {window.tier for window in windows} == {SaleTier.FLASH_SLOT}

    def test_a_mega_day_has_the_campaign_plus_the_slots(self) -> None:
        windows = day_windows(date(2026, 12, 12))

        assert len(windows) == len(FLASH_SALE_HOURS) + 1
        assert any(window.tier is SaleTier.MEGA for window in windows)

    def test_overlapping_windows_are_reported_strongest_first(self) -> None:
        # 21:00 on 12.12 is both a mega day and a flash slot.
        windows = active_windows(ict(2026, 12, 12, 21, 30))

        assert [window.tier for window in windows] == [
            SaleTier.MEGA,
            SaleTier.FLASH_SLOT,
        ]

    def test_a_flash_slot_lasts_an_hour(self) -> None:
        assert current_tier(ict(2026, 5, 20, 12, 30)) is SaleTier.FLASH_SLOT
        assert current_tier(ict(2026, 5, 20, 13, 30)) is SaleTier.QUIET


class TestTimezone:
    def test_sale_days_are_vietnamese_calendar_days(self) -> None:
        """12.12 in Vietnam starts at 17:00 UTC on the 11th.

        A user in another timezone must see the same campaign the storefront is running, not
        one shifted by their own offset.
        """
        just_before = datetime(2026, 12, 11, 16, 59, tzinfo=UTC)
        just_after = datetime(2026, 12, 11, 17, 1, tzinfo=UTC)

        assert current_tier(just_before) is not SaleTier.MEGA
        assert current_tier(just_after) is SaleTier.MEGA

    def test_a_naive_datetime_is_treated_as_utc(self) -> None:
        aware = datetime(2026, 12, 12, 6, 0, tzinfo=UTC)
        naive = datetime(2026, 12, 12, 6, 0)

        assert current_tier(naive) is current_tier(aware)


class TestCadence:
    def test_quiet_days_are_cheap(self) -> None:
        assert recommended_interval(ict(2026, 5, 20, 13, 30)) == timedelta(hours=6)

    def test_a_mega_sale_is_scanned_hard(self) -> None:
        assert recommended_interval(ict(2026, 12, 12, 14, 30)) == timedelta(minutes=5)

    def test_cadence_tightens_before_a_big_window_opens(self) -> None:
        """23:30 on 11.12 local: quiet, but 12.12 opens in half an hour."""
        moment = ict(2026, 12, 11, 23, 30)

        assert current_tier(moment) is SaleTier.QUIET
        assert recommended_interval(moment) == timedelta(minutes=5)

    def test_payday_sits_between_the_two(self) -> None:
        interval = recommended_interval(ict(2026, 5, 15, 13, 30))

        assert timedelta(minutes=5) < interval < timedelta(hours=6)


class TestNextWindow:
    def test_finds_the_next_mega_sale_a_year_out(self) -> None:
        window = next_window(ict(2026, 12, 12, 14, 30), min_tier=SaleTier.MEGA)

        assert window is not None
        assert window.name == "9.9 Mega Sale"
        assert window.start > ict(2026, 12, 12, 14, 30)

    def test_skips_a_window_that_has_already_started(self) -> None:
        moment = ict(2026, 5, 20, 12, 30)  # inside the 12:00 flash slot

        window = next_window(moment, min_tier=SaleTier.FLASH_SLOT)

        assert window is not None
        assert window.start > moment
        assert window.name == "Flash Sale 15:00"

    def test_returns_none_when_nothing_qualifies_in_the_horizon(self) -> None:
        assert (
            next_window(ict(2026, 5, 20), min_tier=SaleTier.MEGA, horizon_days=1)
            is None
        )


class TestTierClassification:
    """Which tiers count as "loud", asked by name rather than by ordinal.

    The UI needs this answer to decide how much to shout. It lives in core because "is 12.12
    a big day" is a fact about Shopee's calendar, not a styling choice — and because a view
    asking it as `tierLevel >= 3` encodes the enum's current numbering, so inserting a tier
    silently reclassifies every day.
    """

    @pytest.mark.parametrize(
        ("tier", "peak"),
        [
            (SaleTier.QUIET, False),
            (SaleTier.FLASH_SLOT, False),
            (SaleTier.PAYDAY, False),
            (SaleTier.DOUBLE_DATE, True),
            (SaleTier.MEGA, True),
        ],
    )
    def test_peak_is_the_campaign_tiers(self, tier: SaleTier, peak: bool) -> None:
        assert is_peak(tier) is peak

    @pytest.mark.parametrize("tier", list(SaleTier))
    def test_only_a_quiet_day_is_not_elevated(self, tier: SaleTier) -> None:
        assert is_elevated(tier) is (tier is not SaleTier.QUIET)

    def test_classification_is_membership_not_a_threshold(self) -> None:
        """The property that makes inserting a tier safe.

        A view asking `tier >= 3` reclassifies every day the moment a member is inserted
        anywhere below the top. Membership does not: the set names the two campaign tiers, so
        a new tier is non-peak until someone decides otherwise. Asserting the *names* is what
        makes this fail on an accidental reclassification — comparing `is_peak` against
        `PEAK_TIERS` would only restate the definition.
        """
        assert {tier.name for tier in SaleTier if is_peak(tier)} == {
            "DOUBLE_DATE",
            "MEGA",
        }
        assert all(tier in SaleTier for tier in PEAK_TIERS)

    def test_peak_days_scan_harder_than_quiet_ones(self) -> None:
        """The classification has to agree with the cadence it claims to describe."""
        slowest_peak = max(SCAN_INTERVAL_SECONDS[tier] for tier in PEAK_TIERS)

        assert slowest_peak < SCAN_INTERVAL_SECONDS[SaleTier.QUIET]
