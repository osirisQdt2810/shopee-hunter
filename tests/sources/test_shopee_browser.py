"""The browser adapter's pure decision: is this URL a verification wall?

Everything else in this adapter needs a real Chromium, so it lives in the live tier. This
classification does not, and it is the one that decides whether the app tells a user to
*wait* or to *sign in* — the difference between an actionable message and someone retrying a
block that is never going to clear (ADR-004).
"""

from __future__ import annotations

import pytest

from shopee_hunter.core.errors import SourceAuthRequired
from shopee_hunter.sources.shopee_browser import (
    INTERSTITIAL_MARKERS,
    ShopeeBrowserSource,
)


@pytest.fixture
def adapter(settings) -> ShopeeBrowserSource:
    settings.demo_mode = False
    return ShopeeBrowserSource(settings)


class TestInterstitialDetection:
    @pytest.mark.parametrize("marker", INTERSTITIAL_MARKERS)
    def test_every_known_wall_is_recognised(self, adapter, marker: str) -> None:
        with pytest.raises(SourceAuthRequired):
            adapter._assert_not_interstitial(f"https://shopee.vn{marker}?redirect=x")

    def test_the_real_observed_redirect_is_recognised(self, adapter) -> None:
        """The exact URL the live run was bounced to, kept as a regression anchor."""
        observed = (
            "https://shopee.vn/verify/traffic/error"
            "?not_support_login=false&is_logged_in=false&type=4"
        )

        with pytest.raises(SourceAuthRequired):
            adapter._assert_not_interstitial(observed)

    def test_an_ordinary_search_url_passes(self, adapter) -> None:
        adapter._assert_not_interstitial("https://shopee.vn/search?keyword=tai+nghe")

    def test_a_product_url_passes(self, adapter) -> None:
        adapter._assert_not_interstitial("https://shopee.vn/product/55/1001")

    def test_the_message_says_how_to_fix_it(self, adapter) -> None:
        """`SourceAuthRequired` is only useful if it tells the user what to actually do."""
        with pytest.raises(SourceAuthRequired) as caught:
            adapter._assert_not_interstitial("https://shopee.vn/verify/traffic/error")

        message = str(caught.value)
        assert "headless" in message
        assert "sign into Shopee" in message or "sign in" in message
