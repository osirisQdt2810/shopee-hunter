"""The settings values that are load-bearing for how hard this app hits Shopee.

Most settings are preferences. These two are not: they decide the request rate, and a bad
value is not "the UI looks odd", it is an IP that stops being served mid-sale (ADR-007).
"""

from __future__ import annotations

import pytest

from shopee_hunter.core.models import SearchQuery
from shopee_hunter.core.settings import RateLimitSettings, ScanSettings


class TestRequestRate:
    def test_the_default_is_deliberately_slow(self) -> None:
        assert RateLimitSettings().requests_per_second == 0.5

    @pytest.mark.parametrize(
        ("given", "expected"), [(0.0, 0.01), (-1.0, 0.01), (5.1, 5.0), (1000.0, 5.0)]
    )
    def test_an_out_of_range_rate_is_clamped_not_refused(
        self, given: float, expected: float
    ) -> None:
        """Persisted values clamp; they never stop the app opening (ADR-009).

        Both bounds in this file behave the same way on purpose. Having one raise and the
        other clamp left the bricked-launch failure mode live for whichever field was not
        thought about, while the docstring of the one that clamped implied the rule was
        general.
        """
        assert RateLimitSettings(requests_per_second=given).requests_per_second == (
            expected
        )

    def test_a_reckless_rate_is_clamped_toward_safety_not_away(self) -> None:
        """Clamping must never hand the user the dangerous number they asked for."""
        assert RateLimitSettings(requests_per_second=50.0).requests_per_second == 5.0


class TestItemsPerWatch:
    """The bound exists because this number multiplies into requests.

    ``SearchQuery.page_count`` is derived from it and each page is a separate request. The
    limiter charges per request, so a large value can no longer burst past the bucket — but
    it can still make one watch monopolise the budget while the others wait, and nobody
    reads five pages of search results anyway.
    """

    def test_the_default_is_a_single_page(self) -> None:
        assert (
            SearchQuery("tai nghe", limit=ScanSettings().items_per_watch).page_count
            == 1
        )

    @pytest.mark.parametrize(
        ("given", "expected"), [(0, 1), (-1, 1), (301, 300), (10_000, 300)]
    )
    def test_an_out_of_range_span_is_clamped_not_refused(
        self, given: int, expected: int
    ) -> None:
        """Clamping, because this value is persisted and ADR-009 governs persisted values.

        `AppSettings.load` turns any validation error into a fatal `ConfigError`, so raising
        here would let a settings file written by a build that allowed 600 stop a build that
        does not from starting at all. Losing the tail of one search is the better failure.
        """
        assert ScanSettings(items_per_watch=given).items_per_watch == expected

    def test_a_settings_file_beyond_the_bound_still_loads(self, tmp_path) -> None:
        """The regression that matters: an out-of-range value must not brick the launch."""
        from shopee_hunter.core.settings import AppSettings

        user = tmp_path / "settings.toml"
        user.write_text("[scan]\nitems_per_watch = 600\n", encoding="utf-8")

        settings = AppSettings.load(user=user, env={})

        assert settings.scan.items_per_watch == 300

    def test_the_ceiling_is_a_handful_of_pages(self) -> None:
        highest = ScanSettings(items_per_watch=300)

        assert SearchQuery("tai nghe", limit=highest.items_per_watch).page_count == 5
