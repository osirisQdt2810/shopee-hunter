"""Shopee's wire format → ``core.models``. Pure functions, no I/O, no Qt.

Every transport (raw HTTP, browser, affiliate API) ends up here, so the quirks of Shopee's
JSON are written down exactly once and pinned by captured fixtures. The quirks that matter:

* money is an integer scaled by 100_000 (``12900000000`` is 129,000 ₫);
* a search hit wraps the real payload in ``item_basic``; a product-detail hit does not;
* ``raw_discount`` is a seller-controlled percentage — parsed, never trusted (ADR-005);
* ``item_rating.rating_count`` is a histogram *list*, whose element 0 is the total;
* images are content hashes that need a CDN prefix;
* an out-of-stock or unavailable listing can carry ``price: -1``.

When a field we depend on is missing, this raises :class:`ParseError` naming it. That is
deliberate: silently defaulting a price to 0 would put "100% off!" in front of a user.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Optional

from ..core.errors import ParseError
from ..core.models import Currency, Money, Product, Shop

# Shopee serves images from a regional CDN; the item payload carries only the hash.
IMAGE_CDN = "https://down-vn.img.susercontent.com/file/"

# API-level error objects rather than HTTP statuses. These arrive with HTTP 200 and an empty
# item list, which is the single most important fact in this file: treating them as "no
# results" is the bug this whole design exists to avoid.
#
# `10` / `99` — "server busy": rate limiting or soft anti-bot. Backing off helps.
ERROR_BLOCKED_CODES = frozenset({10, 99})

# `90309999` — observed live on 2026-08-23. Shopee's risk-control refusal: the whole
# `/search` page redirects to `/verify/traffic/error?...&is_logged_in=false`, and every
# search API call comes back with this code inside an obfuscated envelope
# (`{"0":…,"1":…,"error":90309999}`) rather than the usual `{"error":…,"error_msg":…}`.
# Backing off does NOT help — an anonymous session is refused however patiently it waits, so
# this is an auth problem and the message has to say so.
ERROR_AUTH_CODES = frozenset({90309999, 90310000})


def _require(payload: Mapping[str, Any], field: str, *, source: str) -> Any:
    if field not in payload:
        raise ParseError(
            f"expected field {field!r} is absent — Shopee's wire format probably changed; "
            f"re-capture the fixture with scripts/capture_fixture.py",
            source=source,
        )
    return payload[field]


def _number(value: Any, field: str, *, where: str, source: str) -> Optional[float]:
    """Read one optional numeric wire field, or raise `ParseError` naming it.

    The absent/unreadable split this enforces is the difference between a listing that
    reports nothing and a wire format that moved. Coercing the second case to a default is
    the single most dangerous habit in a parser for this app: the value silently becomes a
    neutral number, every downstream judgement made from it is wrong in the *safe-looking*
    direction, and nothing raises.

    Absent (missing, ``None``, ``""``) returns ``None``. Anything else must be a finite
    number — ``float("nan")`` and ``float("1e400")`` both succeed, and a NaN propagates into
    comparisons that quietly answer ``False``.
    """
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ParseError(
            f"{where}: {field} is not numeric ({value!r})", source=source
        ) from exc
    if number != number or number in (float("inf"), float("-inf")):
        raise ParseError(f"{where}: {field} is not finite ({value!r})", source=source)
    return number


def _rating(
    payload: Mapping[str, Any], *, where: str, source: str
) -> tuple[Optional[float], int]:
    """Extract ``(stars, count)`` from ``item_rating``.

    ``rating_count`` is a histogram: ``[total, 1-star, 2-star, 3-star, 4-star, 5-star]``.
    Element 0 is the total, and older payloads occasionally omit the list entirely.

    A non-numeric ``rating_star`` raises rather than becoming ``None``: ``None`` flips
    ``rating_is_credible``, which adds ``UNRATED_SELLER`` and its score penalty to *every*
    listing on the page at once — a page-wide reranking caused by a field nobody noticed had
    changed shape.
    """
    rating = payload.get("item_rating") or {}
    counts = rating.get("rating_count")
    total = 0
    # `str` is a Sequence, so a `rating_count` of "1234" would index to "1" and parse as a
    # count of one. Excluding str/bytes keeps the histogram branch about actual histograms.
    if isinstance(counts, Sequence) and not isinstance(counts, (str, bytes)) and counts:
        total = int(
            _number(counts[0], "rating_count[0]", where=where, source=source) or 0
        )
    elif isinstance(counts, (int, float)) and not isinstance(counts, bool):
        total = int(counts)
    elif isinstance(counts, (str, bytes)):
        total = int(_number(counts, "rating_count", where=where, source=source) or 0)
    stars_value = _number(
        rating.get("rating_star"), "rating_star", where=where, source=source
    )
    return stars_value, total


def _image_url(payload: Mapping[str, Any]) -> str:
    image = payload.get("image") or ""
    if not image:
        images = payload.get("images") or []
        image = images[0] if images else ""
    return f"{IMAGE_CDN}{image}" if image else ""


def _vouchers(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Human-readable voucher/promo labels, best-effort.

    Shopee moves these between keys between versions, so this is intentionally forgiving:
    a missing badge costs the user nothing, unlike a missing price.
    """
    labels: list[str] = []
    voucher = payload.get("voucher_info") or {}
    if isinstance(voucher, Mapping):
        promotion = voucher.get("promotion_id")
        discount = voucher.get("voucher_code") or voucher.get("label")
        if discount:
            labels.append(str(discount))
        elif promotion:
            labels.append(f"voucher #{promotion}")
    for badge in (
        payload.get("badge_icon_type", [])
        if isinstance(payload.get("badge_icon_type"), list)
        else []
    ):
        labels.append(str(badge))
    return tuple(labels)


def parse_shop(payload: Mapping[str, Any]) -> Shop:
    """Build the seller from whatever credibility signals the payload carries."""
    return Shop(
        shop_id=int(payload.get("shopid") or payload.get("shop_id") or 0),
        name=str(payload.get("shop_name") or payload.get("username") or ""),
        location=str(payload.get("shop_location") or ""),
        rating=payload.get("shop_rating"),
        is_official=bool(
            payload.get("is_official_shop") or payload.get("shopee_verified")
        ),
        is_preferred=bool(
            payload.get("is_preferred_plus_seller")
            or payload.get("is_preferred_seller")
        ),
    )


def parse_item(
    payload: Mapping[str, Any],
    *,
    currency: Currency = Currency.VND,
    captured_at: Optional[datetime] = None,
    source: str = "shopee",
) -> Product:
    """Parse one listing.

    Accepts either the search shape (payload wrapped in ``item_basic``) or a bare item
    payload, so the same function serves search, product detail, and flash sale.

    Args:
        payload: One entry from ``items``, or a bare item object.
        currency: Storefront currency, used to tag every ``Money``.
        captured_at: Observation time; defaults to now (UTC).
        source: Adapter id, for error attribution.

    Raises:
        ParseError: A field the app depends on is missing or non-numeric.
    """
    basic = (
        payload.get("item_basic")
        if isinstance(payload.get("item_basic"), Mapping)
        else payload
    )

    try:
        item_id = int(_require(basic, "itemid", source=source))
        shop_id = int(_require(basic, "shopid", source=source))
        # Converted inside the guard: Money.from_shopee raises on a non-numeric price rather
        # than defaulting to 0, and that has to surface as a ParseError naming the item.
        price = Money.from_shopee(_require(basic, "price", source=source), currency)
        before_raw = basic.get("price_before_discount")
        before = Money.from_shopee(before_raw, currency) if before_raw else None
    except (TypeError, ValueError) as exc:
        raise ParseError(
            f"non-numeric identity/price in item payload: {exc}", source=source
        ) from exc

    name = str(basic.get("name") or "").strip()
    if not name:
        raise ParseError(f"item {shop_id}_{item_id} has no name", source=source)
    # Shopee sets price_before_discount to 0 (or below the price) on undiscounted listings.
    if before is not None and before.amount <= price.amount:
        before = None

    where = f"item {shop_id}_{item_id}"
    stars, rating_count = _rating(basic, where=where, source=source)

    # An ABSENT raw_discount means "this listing claims nothing" and is ordinary. A value
    # that is present but unreadable means the wire format moved, and defaulting it to 0 is
    # how this app would betray its own purpose: with claimed_discount_pct == 0 the
    # comparison in core/deals.py can never exceed the inflation tolerance, so CLAIM_INFLATED
    # never fires, is_genuine stops filtering, the score penalty stops applying, and every
    # permanently-"-50%" listing — exactly what ADR-005 exists to suppress — ranks as
    # verified. The card then renders "Shopee claims -0%" in calm grey, so the fake listing
    # looks *more* trustworthy than an honest one.
    claimed = int(
        _number(basic.get("raw_discount"), "raw_discount", where=where, source=source)
        or 0
    )

    return Product(
        item_id=item_id,
        shop_id=shop_id,
        name=name,
        price=price,
        price_before_discount=before,
        claimed_discount_pct=max(0, min(claimed, 100)),
        rating=stars,
        rating_count=rating_count,
        sold_count=int(
            _number(
                basic.get("historical_sold") or basic.get("sold"),
                "historical_sold",
                where=where,
                source=source,
            )
            or 0
        ),
        stock=basic.get("stock"),
        image_url=_image_url(basic),
        shop=parse_shop(basic),
        is_flash_sale=bool(
            basic.get("flash_sale_stock") or basic.get("is_on_flash_sale")
        ),
        has_free_shipping=bool(basic.get("show_free_shipping")),
        vouchers=_vouchers(basic),
        captured_at=captured_at or datetime.now(UTC),
    )


def check_api_error(payload: Mapping[str, Any], *, source: str) -> None:
    """Raise if the body carries an API-level error, even under HTTP 200.

    Shopee answers a bot-flagged or throttled request with ``{"error": 10, "items": []}`` and
    a perfectly healthy status line. Every adapter calls this **before** looking at ``items``.

    Raises:
        SourceAuthRequired: Risk control wants a signed-in session; waiting cannot help.
        SourceBlocked: Rate limit or soft anti-bot; backing off can help.
        ParseError: An error code we do not recognise — worth investigating rather than
            silently treating as a block.
    """
    from ..core.errors import (  # local: no import cycle
        SourceAuthRequired,
        SourceBlocked,
    )

    error = payload.get("error")
    if error in (None, 0):
        return
    message = str(payload.get("error_msg") or payload.get("err_msg") or "no message")
    if isinstance(error, int) and error in ERROR_AUTH_CODES:
        raise SourceAuthRequired(
            f"Shopee risk control refused an anonymous session (error {error}). Searching "
            f"this storefront needs a signed-in browser: run once with "
            f"sources.browser.headless = false, log into Shopee in the window that opens, "
            f"and the profile is reused from then on.",
            source=source,
        )
    if isinstance(error, int) and error in ERROR_BLOCKED_CODES:
        raise SourceBlocked(
            f"Shopee refused the request (error {error}: {message}) — anti-bot or rate limit. "
            f"Back off, or use a source that carries a real browser session.",
            source=source,
        )
    raise ParseError(f"Shopee returned error {error}: {message}", source=source)


def parse_search_response(
    payload: Mapping[str, Any],
    *,
    currency: Currency = Currency.VND,
    captured_at: Optional[datetime] = None,
    source: str = "shopee",
) -> list[Product]:
    """Parse a ``/api/v4/search/search_items`` body into products.

    An empty ``items`` list with no error is a genuine "no matches" and returns ``[]``.
    Individual unparseable entries are skipped rather than failing the whole page — one
    malformed listing among sixty should not cost the user the other fifty-nine — but a
    page where *nothing* parses raises, because that is a wire-format change.

    Raises:
        SourceBlocked: The body carries a blocking error code.
        ParseError: The body has no ``items`` key at all, or no entry could be parsed.
    """
    check_api_error(payload, source=source)

    items = payload.get("items")
    if items is None:
        raise ParseError("response has no 'items' key", source=source)
    if not items:
        return []

    products: list[Product] = []
    failures: list[str] = []
    for entry in items:
        if not isinstance(entry, Mapping):
            failures.append(f"non-object entry: {type(entry).__name__}")
            continue
        try:
            products.append(
                parse_item(
                    entry, currency=currency, captured_at=captured_at, source=source
                )
            )
        except ParseError as exc:
            failures.append(str(exc))

    if not products:
        raise ParseError(
            f"none of {len(items)} items could be parsed; first reason: "
            f"{failures[0] if failures else 'unknown'}",
            source=source,
        )
    return products


def parse_flash_sale_response(
    payload: Mapping[str, Any],
    *,
    currency: Currency = Currency.VND,
    captured_at: Optional[datetime] = None,
    source: str = "shopee",
) -> list[Product]:
    """Parse a flash-sale batch body.

    The flash-sale endpoints nest the list under ``data.items`` instead of a top-level
    ``items``, and every entry is already flash-priced — so the flag is forced on rather than
    inferred, which keeps these observations out of the price baseline (ADR-005).
    """
    check_api_error(payload, source=source)
    data = payload.get("data")
    items: Iterable[Any] = []
    if isinstance(data, Mapping):
        items = data.get("items") or []
    elif payload.get("items"):
        items = payload["items"]

    products: list[Product] = []
    for entry in items:
        if not isinstance(entry, Mapping):
            continue
        try:
            product = parse_item(
                entry, currency=currency, captured_at=captured_at, source=source
            )
        except ParseError:
            continue
        products.append(product if product.is_flash_sale else _force_flash(product))
    return products


def _force_flash(product: Product) -> Product:
    """Mark a product as flash-priced (the endpoint guarantees it; the payload may not)."""
    from dataclasses import replace

    return replace(product, is_flash_sale=True)
