"""The official, sanctioned transport: Shopee's Affiliate Open API (GraphQL).

Preferred whenever the user has keys, because it is the only path Shopee actually invites us
to use: documented, stable, rate-limited by contract rather than by anti-bot guesswork. Its
catalogue coverage is narrower than site search, which is why it heads a fallback chain
instead of replacing it (ADR-004).

Auth is a SHA-256 signature over ``app_id + timestamp + payload + app_secret``, sent as an
``Authorization: SHA256 Credential=…`` header. No secret ever appears in a URL or a log.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Any, Optional

import httpx

from ..core.errors import (
    ParseError,
    SourceAuthRequired,
    SourceBlocked,
    SourceUnavailable,
)
from ..core.models import Currency, Money, Product, SearchQuery, Shop
from ..core.rate_limit import AsyncTokenBucket
from ..core.settings import AppSettings
from .base import SourceAdapter
from .registry import register_source

# The affiliate API's own product search. Only the fields we map are requested — a smaller
# document is a smaller thing to break when the schema evolves.
_SEARCH_QUERY = """
query productOfferV2($keyword: String, $limit: Int, $page: Int, $sortType: Int) {
  productOfferV2(keyword: $keyword, limit: $limit, page: $page, sortType: $sortType) {
    nodes {
      itemId
      shopId
      productName
      price
      priceMin
      priceMax
      priceDiscountRate
      ratingStar
      sales
      imageUrl
      shopName
      shopType
      productLink
    }
    pageInfo { page limit hasNextPage }
  }
}
"""


@register_source("affiliate")
class AffiliateApiSource(SourceAdapter):
    """Signed GraphQL calls against the Affiliate Open API."""

    label = "Shopee Affiliate API (official)"
    requires_credentials = True
    supports_flash_sale = False

    def __init__(
        self,
        settings: AppSettings,
        *,
        limiter: Optional[AsyncTokenBucket] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(settings, limiter=limiter)
        self.config = settings.sources.affiliate
        self._client = client
        self._owns_client = client is None

    async def is_available(self) -> bool:
        return bool(
            self.config.enabled and self.config.app_id and self.config.app_secret
        )

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def _sign(self, payload: str, timestamp: int) -> str:
        """Build the ``Authorization`` header value.

        The signature covers the timestamp, so a replayed request expires — which is also why
        a wrong system clock shows up as an auth failure rather than a network one.
        """
        material = f"{self.config.app_id}{timestamp}{payload}{self.config.app_secret}"
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return f"SHA256 Credential={self.config.app_id}, Timestamp={timestamp}, Signature={digest}"

    async def _post(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if not await self.is_available():
            raise SourceAuthRequired(
                "affiliate app_id/app_secret are not configured — add them to "
                "config/secrets.toml or disable this source",
                source=self.id,
            )
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)

        # One token per POST. `_do_search` keeps paging until it has `query.limit` items, so
        # charging once per operation would let a single search fire an unbounded burst
        # (ADR-007).
        await self._throttle("affiliate query")

        payload = json.dumps(
            {"query": query, "variables": variables}, separators=(",", ":")
        )
        timestamp = int(time.time())
        try:
            response = await self._client.post(
                self.config.endpoint,
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": self._sign(payload, timestamp),
                },
            )
        except httpx.TimeoutException as exc:
            raise SourceUnavailable("affiliate API timeout", source=self.id) from exc
        except httpx.HTTPError as exc:
            raise SourceUnavailable(
                f"affiliate API transport error: {exc}", source=self.id
            ) from exc

        if response.status_code in (401, 403):
            raise SourceAuthRequired(
                f"affiliate API rejected the credentials (HTTP {response.status_code}) — check "
                f"app_id/app_secret and the system clock (the signature is timestamped)",
                source=self.id,
            )
        if response.status_code == 429:
            raise SourceBlocked("affiliate API rate limit (HTTP 429)", source=self.id)
        if response.status_code != 200:
            raise SourceUnavailable(
                f"affiliate API HTTP {response.status_code}", source=self.id
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise ParseError(
                f"affiliate API returned non-JSON: {exc}", source=self.id
            ) from exc

        if body.get("errors"):
            first = (
                body["errors"][0]
                if isinstance(body["errors"], list)
                else body["errors"]
            )
            message = first.get("message") if isinstance(first, dict) else str(first)
            # GraphQL reports auth problems in the body with a 200, so classify here too.
            if message and "auth" in message.lower():
                raise SourceAuthRequired(f"affiliate API: {message}", source=self.id)
            raise ParseError(f"affiliate API error: {message}", source=self.id)

        data = body.get("data")
        if not isinstance(data, dict):
            raise ParseError(
                "affiliate API response has no data object", source=self.id
            )
        return data

    def _number(
        self, node: dict[str, Any], field: str, item_id: int
    ) -> Optional[float]:
        """Read one optional numeric field, or raise `ParseError` naming it.

        Absent (missing, ``None``, ``""``) means "the API did not report this" and returns
        ``None``. Anything else must be a finite number: a value that is present but
        unreadable means the wire format moved, and coercing it to a default is how this
        adapter used to report a page of items as no deals at all.

        The finiteness check is not pedantry — ``float("nan")`` and ``float("1e400")``
        succeed, and a NaN rating propagates into comparisons that silently answer False.
        """
        raw = node.get(field)
        if raw is None or raw == "":
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ParseError(
                f"affiliate node {item_id}: {field} is not numeric ({raw!r})",
                source=self.id,
            ) from exc
        if not math.isfinite(value):
            raise ParseError(
                f"affiliate node {item_id}: {field} is not finite ({raw!r})",
                source=self.id,
            )
        return value

    def _to_product(self, node: dict[str, Any]) -> Product:
        """Map an affiliate node onto the shared model.

        The affiliate schema reports real currency units (not Shopee's ×100_000 wire scale)
        and a discount *rate* rather than an original price — so the original is reconstructed
        from the rate, and kept as the claim it is.
        """
        try:
            item_id = int(node["itemId"])
            shop_id = int(node["shopId"])
            price = round(float(node["price"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ParseError(
                f"affiliate node missing itemId/shopId/price: {exc}", source=self.id
            ) from exc

        currency = Currency(self.settings.storefront.currency)
        # An ABSENT rate means "no claim" and is legitimate. A rate that is present but
        # unparseable means the wire format moved, and must say so: defaulting it to 0 sets
        # `claimed_discount_pct=0` on every item, which silently disables CLAIM_INFLATED
        # detection and then filters the whole page out against `scan.min_discount_pct` — the
        # app reports "no deals" mid-sale while the adapter is returning a full page.
        rate_raw = node.get("priceDiscountRate")
        if rate_raw is None or rate_raw == "":
            rate = 0
        else:
            try:
                rate = int(float(rate_raw))
            except (TypeError, ValueError, OverflowError) as exc:
                # OverflowError, not just ValueError: `float("inf")` parses fine and only
                # `int()` refuses it, so a rate of "inf" would otherwise escape untyped.
                raise ParseError(
                    f"affiliate node {item_id}: priceDiscountRate is not numeric "
                    f"({rate_raw!r})",
                    source=self.id,
                ) from exc

        # Same absent-vs-unreadable split as the rate above. Truthiness is not the test: an
        # empty list is not "no rating", it is a field that changed shape. Unlike the rate,
        # this one stays a float — and `float()` happily returns nan/inf for "nan"/"1e400",
        # which `int()` would have refused, so it needs the finiteness check `_number` makes.
        rating = self._number(node, "ratingStar", item_id)

        before = (
            Money(round(price / (1 - rate / 100)), currency) if 0 < rate < 100 else None
        )
        shop_type = node.get("shopType") or []
        return Product(
            item_id=item_id,
            shop_id=shop_id,
            name=str(node.get("productName") or "").strip() or f"item {item_id}",
            price=Money(price, currency),
            price_before_discount=before,
            claimed_discount_pct=max(0, min(rate, 100)),
            rating=rating,
            # The affiliate schema exposes no rating count; 0 means the deal engine treats
            # the rating as not-yet-credible, which is the correct conservative reading.
            rating_count=0,
            # Same typed coercion as the rest: `int(node.get("sales") or 0)` was the third
            # instance of the swallow-and-default shape this class was fixed for, and would
            # have thrown a bare ValueError on a `sales` of "2.5k".
            sold_count=int(self._number(node, "sales", item_id) or 0),
            image_url=str(node.get("imageUrl") or ""),
            shop=Shop(
                shop_id=shop_id,
                name=str(node.get("shopName") or ""),
                is_official=any("mall" in str(t).lower() for t in shop_type),
                is_preferred=any("preferred" in str(t).lower() for t in shop_type),
            ),
        )

    # -- adapter contract -------------------------------------------------------
    async def _do_search(self, query: SearchQuery) -> list[Product]:
        collected: list[Product] = []
        page = 1
        while len(collected) < query.limit:
            data = await self._post(
                _SEARCH_QUERY,
                {
                    "keyword": query.keyword,
                    "limit": min(50, query.limit - len(collected)),
                    "page": page,
                    "sortType": 2,  # 2 = by sales; the API's own ordering vocabulary
                },
            )
            offer = data.get("productOfferV2") or {}
            nodes = offer.get("nodes") or []
            # Per-node tolerance, matching `parse_search_response`'s documented policy: one
            # malformed listing among fifty must not cost the user the other forty-nine, but
            # a page where *nothing* parses is a wire-format change and has to say so.
            # Letting a single bad node abort the page would have turned the typed-error fix
            # into a worse failure than the swallowing it replaced.
            failures: list[str] = []
            parsed = 0
            for node in nodes:
                if not isinstance(node, dict):
                    failures.append(f"non-object node: {type(node).__name__}")
                    continue
                try:
                    collected.append(self._to_product(node))
                except ParseError as exc:
                    failures.append(str(exc))
                    continue
                parsed += 1
            if nodes and parsed == 0:
                raise ParseError(
                    f"none of {len(nodes)} affiliate nodes could be parsed; first reason: "
                    f"{failures[0] if failures else 'unknown'}",
                    source=self.id,
                )
            if failures:
                self.log.warning(
                    "skipped %d unparseable affiliate node(s); first: %s",
                    len(failures),
                    failures[0],
                )
            if not (offer.get("pageInfo") or {}).get("hasNextPage") or not nodes:
                break
            page += 1

        if query.max_price is not None:
            collected = [
                p for p in collected if p.price.amount <= query.max_price.amount
            ]
        return collected[: query.limit]

    async def _do_fetch_item(self, item_id: int, shop_id: int) -> Product:
        # The affiliate schema has no by-id lookup; a keyword search cannot stand in for one,
        # and silently returning the wrong item would corrupt price history.
        raise SourceUnavailable(
            "the affiliate API has no single-item endpoint; use the browser or web source "
            "to refresh one listing",
            source=self.id,
        )
