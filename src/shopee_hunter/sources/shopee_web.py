"""Plain-HTTP adapter against Shopee's internal ``/api/v4`` JSON endpoints.

Honest about what this is: the endpoints the website's own front end calls. They return
everything we need and they are protected. Without cookies from a real browser session, most
requests come back HTTP 200 with ``{"error": 10}`` — which this adapter surfaces as
``SourceBlocked`` rather than as "no results" (ADR-004, ADR-007).

So this transport is the *fallback*, not the plan. It shines when the user has pasted a
cookie string from their own logged-in browser; otherwise the browser adapter is the one
that works.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from ..core.errors import SourceAuthRequired, SourceBlocked, SourceUnavailable
from ..core.models import Product, SearchQuery
from ..core.rate_limit import AsyncTokenBucket
from ..core.settings import AppSettings
from .base import SourceAdapter
from .parse import parse_flash_sale_response, parse_item, parse_search_response
from .registry import register_source

# Shopee's search page size is fixed; asking for more is silently truncated.
PAGE_SIZE = 60

# HTTP statuses that mean "the bouncer said no" rather than "the server is unwell".
_BLOCKING_STATUSES = frozenset({403, 429})


@register_source("web")
class ShopeeWebSource(SourceAdapter):
    """Talks to ``/api/v4/*`` over httpx, using cookies the user supplies."""

    label = "Shopee web API (cookies)"
    supports_flash_sale = True

    def __init__(
        self,
        settings: AppSettings,
        *,
        limiter: Optional[AsyncTokenBucket] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(settings, limiter=limiter)
        self.config = settings.sources.web
        # An injected client is how the offline tests drive this adapter through respx
        # without a socket, and how a caller can share one connection pool.
        self._client = client
        self._owns_client = client is None

    # -- transport --------------------------------------------------------------
    @property
    def base_url(self) -> str:
        return f"https://{self.domain}"

    def _headers(self, referer: str) -> dict[str, str]:
        """Headers that make the request look like the website's own fetch.

        ``Referer`` and ``X-API-SOURCE`` are not decoration: the endpoints 403 without them
        even when the cookies are valid.
        """
        headers = {
            "User-Agent": self.config.user_agent,
            "Accept": "application/json",
            "Accept-Language": f"{self.settings.storefront.language},en;q=0.8",
            "Referer": referer,
            "X-API-SOURCE": "pc",
            "X-Requested-With": "XMLHttpRequest",
            "X-Shopee-Language": self.settings.storefront.language,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        if self.config.cookie_string:
            headers["Cookie"] = self.config.cookie_string
            csrf = _csrf_from_cookies(self.config.cookie_string)
            if csrf:
                headers["X-CSRFToken"] = csrf
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.config.timeout_seconds,
                follow_redirects=True,
                http2=False,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def is_available(self) -> bool:
        return self.config.enabled

    async def _get_json(
        self, path: str, params: dict[str, Any], referer: str
    ) -> dict[str, Any]:
        """One GET, mapped onto our typed errors.

        Every failure mode Shopee has is converted here, so the parse layer above can assume
        it is looking at a real body:
        * 403/429 → blocked (their anti-bot, or our own pace);
        * an HTML body → blocked (a captcha/interstitial page, not JSON);
        * 5xx / timeout / connection error → unavailable (retryable).

        Charges the rate limiter first: a paginated search calls this once per page, and each
        call is a real request that has to pay for itself (ADR-007).
        """
        await self._throttle(path)
        client = await self._get_client()
        try:
            response = await client.get(
                path, params=params, headers=self._headers(referer)
            )
        except httpx.TimeoutException as exc:
            raise SourceUnavailable(
                f"timeout after {self.config.timeout_seconds}s", source=self.id
            ) from exc
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"transport error: {exc}", source=self.id) from exc

        if response.status_code in _BLOCKING_STATUSES:
            raise SourceBlocked(
                f"HTTP {response.status_code} on {path} — Shopee's anti-bot refused us"
                + ("" if self.config.cookie_string else " (no cookies configured)"),
                source=self.id,
            )
        if response.status_code >= 500:
            raise SourceUnavailable(
                f"HTTP {response.status_code} on {path}", source=self.id
            )
        if response.status_code != 200:
            raise SourceUnavailable(
                f"unexpected HTTP {response.status_code} on {path}", source=self.id
            )

        content_type = response.headers.get("content-type", "")
        if "json" not in content_type.lower():
            # A captcha or login interstitial: HTML with a 200. Not a parse problem.
            raise SourceBlocked(
                f"{path} returned {content_type or 'no content-type'} instead of JSON — "
                f"captcha or login wall",
                source=self.id,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SourceBlocked(
                f"{path} returned unparseable JSON: {exc}", source=self.id
            ) from exc
        if not isinstance(payload, dict):
            raise SourceUnavailable(
                f"{path} returned a {type(payload).__name__}, not an object",
                source=self.id,
            )
        return payload

    # -- adapter contract -------------------------------------------------------
    async def _do_search(self, query: SearchQuery) -> list[Product]:
        referer = f"{self.base_url}/search?keyword={query.keyword}"
        collected: list[Product] = []

        for page in range(query.page_count):
            params: dict[str, Any] = {
                "by": query.order.value,
                "keyword": query.keyword,
                "limit": PAGE_SIZE,
                "newest": page * PAGE_SIZE,
                "order": "asc" if query.order.value == "price" else "desc",
                "page_type": "search",
                "scenario": "PAGE_GLOBAL_SEARCH",
                "version": 2,
            }
            # Shopee wants price filters in its scaled integers, same as it returns them.
            if query.min_price is not None:
                params["price_min"] = query.min_price.amount * 100_000
            if query.max_price is not None:
                params["price_max"] = query.max_price.amount * 100_000
            if query.min_rating is not None:
                params["rating_filter"] = int(query.min_rating)
            if query.category_id is not None:
                params["catid"] = query.category_id
            if query.shop_id is not None:
                params["shopid"] = query.shop_id
            if query.official_only:
                params["official_mall"] = "true"
            if query.free_shipping_only:
                params["free_shipping"] = "true"

            payload = await self._get_json(
                "/api/v4/search/search_items", params, referer
            )
            page_products = parse_search_response(
                payload, currency=self.currency, source=self.id
            )
            collected.extend(page_products)

            # Stop as soon as Shopee says there is no more, or it gave us a short page —
            # paging past the end is pure waste against a rate limit we are trying to respect.
            if payload.get("nomore") or len(page_products) < PAGE_SIZE:
                break
            if len(collected) >= query.limit:
                break

        return collected[: query.limit]

    async def _do_fetch_item(self, item_id: int, shop_id: int) -> Product:
        payload = await self._get_json(
            "/api/v4/pdp/get_pc",
            {"item_id": item_id, "shop_id": shop_id, "detail_level": 0},
            f"{self.base_url}/product/{shop_id}/{item_id}",
        )
        from .parse import check_api_error

        check_api_error(payload, source=self.id)
        data = payload.get("data") or {}
        item = data.get("item") if isinstance(data, dict) else None
        return parse_item(item or data, currency=self.currency, source=self.id)

    async def _do_flash_sale(self, limit: int) -> list[Product]:
        payload = await self._get_json(
            "/api/v4/flash_sale/get_all_itemids",
            {"limit": min(limit, PAGE_SIZE), "need_personalize": "true"},
            f"{self.base_url}/flash_sale",
        )
        return parse_flash_sale_response(
            payload, currency=self.currency, source=self.id
        )[:limit]

    async def check_credentials(self) -> None:
        """Raise if this adapter has no chance of working. Used by the Settings view."""
        if not self.config.cookie_string:
            raise SourceAuthRequired(
                "no cookie string configured — paste one from a logged-in browser, or use "
                "the browser source instead",
                source=self.id,
            )


def _csrf_from_cookies(cookie_string: str) -> Optional[str]:
    """Pull ``csrftoken`` out of a raw cookie header, if it is in there."""
    for part in cookie_string.split(";"):
        name, _, value = part.strip().partition("=")
        if name.lower() == "csrftoken" and value:
            return value
    return None
