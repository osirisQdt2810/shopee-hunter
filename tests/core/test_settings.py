"""The settings values that are load-bearing for how hard this app hits Shopee.

Most settings are preferences. These two are not: they decide the request rate, and a bad
value is not "the UI looks odd", it is an IP that stops being served mid-sale (ADR-007).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shopee_hunter.core.models import SearchQuery
from shopee_hunter.core.settings import RateLimitSettings, ScanSettings


class TestRequestRate:
    def test_the_default_is_deliberately_slow(self) -> None:
        assert RateLimitSettings().requests_per_second == 0.5

    @pytest.mark.parametrize("rate", [0.0, -1.0, 5.1, 1000.0])
    def test_an_out_of_range_rate_is_refused(self, rate: float) -> None:
        with pytest.raises(ValidationError):
            RateLimitSettings(requests_per_second=rate)


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

    @pytest.mark.parametrize("value", [0, -1, 301, 10_000])
    def test_an_out_of_range_span_is_refused(self, value: int) -> None:
        with pytest.raises(ValidationError):
            ScanSettings(items_per_watch=value)

    def test_the_ceiling_is_a_handful_of_pages(self) -> None:
        highest = ScanSettings(items_per_watch=300)

        assert SearchQuery("tai nghe", limit=highest.items_per_watch).page_count == 5
