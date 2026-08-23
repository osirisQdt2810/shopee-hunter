"""The httpx adapter, driven through respx — every failure mode Shopee actually has.

The point of these tests is the *classification*: a 403 is a block, an HTML body with a 200 is
a block, a 500 is retryable, and a healthy body is a result. Getting that wrong is what makes
an app report "no deals" during a live sale (ADR-004).
"""

from __future__ import annotations

import httpx
import pytest
import respx

from shopee_hunter.core.errors import (
    SourceAuthRequired,
    SourceBlocked,
    SourceUnavailable,
)
from shopee_hunter.core.models import Money, SearchQuery
from shopee_hunter.sources.shopee_web import ShopeeWebSource

SEARCH_PATH = "https://shopee.vn/api/v4/search/search_items"


def healthy_body(count: int = 2, nomore: bool = True) -> dict:
    return {
        "error": None,
        "nomore": nomore,
        "items": [
            {
                "item_basic": {
                    "itemid": 1000 + index,
                    "shopid": 55,
                    "name": f"Tai nghe {index}",
                    "price": 19_900_000_000,
                    "price_before_discount": 39_900_000_000,
                    "raw_discount": 50,
                    "item_rating": {"rating_star": 4.5, "rating_count": [100]},
                    "historical_sold": 500,
                    "image": "hash",
                }
            }
            for index in range(count)
        ],
    }


@pytest.fixture
def adapter(settings):
    settings.demo_mode = False
    settings.sources.web.enabled = True
    settings.sources.web.max_retries = 1
    settings.sources.web.retry_backoff_seconds = 0.0
    return ShopeeWebSource(settings)


@pytest.fixture
def query():
    return SearchQuery("tai nghe", limit=10)


class TestHappyPath:
    @respx.mock
    async def test_parses_a_search_response(self, adapter, query):
        respx.get(SEARCH_PATH).mock(
            return_value=httpx.Response(200, json=healthy_body())
        )

        products = await adapter.search(query)

        assert [p.item_id for p in products] == [1000, 1001]
        await adapter.aclose()

    @respx.mock
    async def test_sends_the_headers_the_endpoint_requires(self, adapter, query):
        route = respx.get(SEARCH_PATH).mock(
            return_value=httpx.Response(200, json=healthy_body())
        )

        await adapter.search(query)

        request = route.calls[0].request
        # Not decoration: the endpoint 403s without these even with valid cookies.
        assert request.headers["x-api-source"] == "pc"
        assert request.headers["referer"].startswith("https://shopee.vn/search")
        assert "user-agent" in request.headers
        await adapter.aclose()

    @respx.mock
    async def test_price_filters_go_out_in_shopees_wire_scale(self, adapter):
        route = respx.get(SEARCH_PATH).mock(
            return_value=httpx.Response(200, json=healthy_body())
        )

        await adapter.search(
            SearchQuery("tai nghe", limit=10, max_price=Money(500_000))
        )

        assert route.calls[0].request.url.params["price_max"] == str(500_000 * 100_000)
        await adapter.aclose()

    @respx.mock
    async def test_a_cookie_string_is_sent_with_its_csrf_token(self, settings, query):
        settings.demo_mode = False
        settings.sources.web.cookie_string = "SPC_EC=abc; csrftoken=tok123"
        adapter = ShopeeWebSource(settings)
        route = respx.get(SEARCH_PATH).mock(
            return_value=httpx.Response(200, json=healthy_body())
        )

        await adapter.search(query)

        request = route.calls[0].request
        assert request.headers["cookie"] == "SPC_EC=abc; csrftoken=tok123"
        assert request.headers["x-csrftoken"] == "tok123"
        await adapter.aclose()

    @respx.mock
    async def test_stops_paginating_when_shopee_says_nomore(self, adapter):
        route = respx.get(SEARCH_PATH).mock(
            return_value=httpx.Response(200, json=healthy_body(count=2, nomore=True))
        )

        await adapter.search(SearchQuery("tai nghe", limit=180))

        assert (
            route.call_count == 1
        ), "paging past the end burns a rate limit for nothing"
        await adapter.aclose()

    @respx.mock
    async def test_every_page_of_a_search_pays_the_rate_limiter(self, settings):
        """ADR-007, through the real request path rather than a test double.

        A three-page search is three requests and must cost three tokens. It used to cost
        one: the limiter was charged once per `search()` in `_guarded`, while `_do_search`
        looped over the pages underneath it. Nothing was visible at the default
        `items_per_watch` of 60, which yields a single page.
        """
        from shopee_hunter.core.rate_limit import AsyncTokenBucket

        taken = 0
        limiter = AsyncTokenBucket(rate=1e6, burst=1000)
        real_acquire = limiter.acquire

        async def counting_acquire(cost: float = 1.0) -> float:
            nonlocal taken
            taken += 1
            return await real_acquire(cost)

        limiter.acquire = counting_acquire  # type: ignore[method-assign]

        settings.demo_mode = False
        settings.sources.web.enabled = True
        adapter = ShopeeWebSource(settings, limiter=limiter)
        route = respx.get(SEARCH_PATH).mock(
            return_value=httpx.Response(200, json=healthy_body(count=60, nomore=False))
        )

        await adapter.search(SearchQuery("tai nghe", limit=180))

        assert route.call_count == 3
        assert taken == route.call_count, "one token per request, not per search"
        await adapter.aclose()

    @respx.mock
    async def test_an_empty_result_is_not_an_error(self, adapter, query):
        respx.get(SEARCH_PATH).mock(
            return_value=httpx.Response(200, json={"error": None, "items": []})
        )

        assert await adapter.search(query) == []
        await adapter.aclose()


class TestFailureClassification:
    @respx.mock
    @pytest.mark.parametrize("status", [403, 429])
    async def test_anti_bot_statuses_are_blocks(self, adapter, query, status):
        respx.get(SEARCH_PATH).mock(return_value=httpx.Response(status))

        with pytest.raises(SourceBlocked) as caught:
            await adapter.search(query)

        assert str(status) in str(caught.value)
        await adapter.aclose()

    @respx.mock
    async def test_a_block_mentions_the_missing_cookies(self, adapter, query):
        """The message has to be actionable — this is the most common live outcome."""
        respx.get(SEARCH_PATH).mock(return_value=httpx.Response(403))

        with pytest.raises(SourceBlocked, match="no cookies configured"):
            await adapter.search(query)

        await adapter.aclose()

    @respx.mock
    async def test_an_html_body_with_a_200_is_a_block_not_a_parse_error(
        self, adapter, query
    ):
        """A captcha/login interstitial. Classifying it as a parse error would send someone
        hunting a wire-format change that never happened."""
        respx.get(SEARCH_PATH).mock(
            return_value=httpx.Response(
                200, text="<html>captcha</html>", headers={"content-type": "text/html"}
            )
        )

        with pytest.raises(SourceBlocked, match="captcha"):
            await adapter.search(query)

        await adapter.aclose()

    @respx.mock
    async def test_error_10_in_the_body_is_a_block(self, adapter, query):
        respx.get(SEARCH_PATH).mock(
            return_value=httpx.Response(
                200, json={"error": 10, "error_msg": "server busy", "items": []}
            )
        )

        with pytest.raises(SourceBlocked, match="refused"):
            await adapter.search(query)

        await adapter.aclose()

    @respx.mock
    async def test_a_5xx_is_retryable_and_then_unavailable(self, adapter, query):
        route = respx.get(SEARCH_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(SourceUnavailable):
            await adapter.search(query)

        assert route.call_count == 2, "one retry, per settings"
        await adapter.aclose()

    @respx.mock
    async def test_a_timeout_is_unavailable_not_a_block(self, adapter, query):
        respx.get(SEARCH_PATH).mock(side_effect=httpx.ConnectTimeout("too slow"))

        with pytest.raises(SourceUnavailable, match="timeout"):
            await adapter.search(query)

        await adapter.aclose()

    @respx.mock
    async def test_a_5xx_then_success_recovers(self, adapter, query):
        respx.get(SEARCH_PATH).mock(
            side_effect=[
                httpx.Response(503),
                httpx.Response(200, json=healthy_body(count=1)),
            ]
        )

        assert len(await adapter.search(query)) == 1
        await adapter.aclose()


class TestAvailability:
    async def test_disabled_means_unavailable(self, settings):
        settings.sources.web.enabled = False

        assert await ShopeeWebSource(settings).is_available() is False

    async def test_check_credentials_explains_what_to_do(self, adapter):
        with pytest.raises(SourceAuthRequired, match="cookie string"):
            await adapter.check_credentials()

        await adapter.aclose()
