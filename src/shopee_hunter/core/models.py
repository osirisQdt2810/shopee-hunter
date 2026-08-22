"""Domain model: the vocabulary every layer shares.

Everything here is immutable and free of I/O. Adapters convert Shopee's wire format into
these types, the deal engine reasons over them, and the GUI renders them — so a change in
Shopee's JSON never reaches past ``sources/parse.py``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Optional

# Shopee's JSON reports money as an integer scaled by 100_000 ("price": 12900000000 is
# 129,000 ₫). The factor is a wire-format detail, so it lives here next to the conversion
# and nowhere else.
SHOPEE_PRICE_SCALE = 100_000


class Currency(StrEnum):
    """Currencies the app can display. Shopee is per-region, so one per storefront."""

    VND = "VND"
    THB = "THB"
    SGD = "SGD"
    MYR = "MYR"
    PHP = "PHP"
    IDR = "IDR"
    BRL = "BRL"


@dataclass(frozen=True, slots=True, order=True)
class Money:
    """An amount in a currency's *major* unit, held as an int where the currency has no
    minor unit (VND, IDR) and as a rounded int of minor units otherwise.

    Held as an int rather than a float because a 0.5 ₫ rounding error compounding through
    a discount calculation is how a "deal" becomes a lie.
    """

    amount: int
    currency: Currency = Currency.VND

    @classmethod
    def from_shopee(
        cls, raw: int | float | None, currency: Currency = Currency.VND
    ) -> Money:
        """Convert Shopee's scaled integer into real money.

        Args:
            raw: The scaled value from the API (``price``, ``price_before_discount``, …).
                ``None`` and negatives both mean "not sold / not set" and become 0.
            currency: The storefront's currency.

        Returns:
            The amount in whole currency units.

        Raises:
            ValueError: ``raw`` is present but not a number. Deliberately loud: a price we
                cannot read must never silently become 0, because 0 reads as "100% off".
        """
        if raw is None:
            return cls(0, currency)
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            raise ValueError(
                f"price must be numeric, got {type(raw).__name__}: {raw!r}"
            )
        if raw < 0:
            return cls(0, currency)
        return cls(round(raw / SHOPEE_PRICE_SCALE), currency)

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    def __add__(self, other: Money) -> Money:
        self._assert_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._assert_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def _assert_same_currency(self, other: Money) -> None:
        if self.currency is not other.currency:
            raise ValueError(
                f"cannot combine {self.currency.value} with {other.currency.value}"
            )

    def __str__(self) -> str:
        return f"{self.amount:,} {self.currency.value}"


@dataclass(frozen=True, slots=True)
class Shop:
    """The seller behind a listing. Credibility signals, not decoration: a 90% discount
    from a shop with no ratings is the shape of a scam listing."""

    shop_id: int
    name: str = ""
    location: str = ""
    rating: Optional[float] = None
    is_official: bool = False
    is_preferred: bool = False

    @property
    def trust_level(self) -> int:
        """0 = unknown seller, 1 = preferred, 2 = official Shopee Mall."""
        if self.is_official:
            return 2
        if self.is_preferred:
            return 1
        return 0


@dataclass(frozen=True, slots=True)
class Product:
    """One listing at one point in time.

    ``price_before_discount`` is Shopee's *claim* about the original price. It is stored
    but never trusted: the deal engine compares against observed history instead.
    """

    item_id: int
    shop_id: int
    name: str
    price: Money
    price_before_discount: Optional[Money] = None
    claimed_discount_pct: int = 0
    rating: Optional[float] = None
    rating_count: int = 0
    sold_count: int = 0
    stock: Optional[int] = None
    image_url: str = ""
    shop: Optional[Shop] = None
    is_flash_sale: bool = False
    has_free_shipping: bool = False
    vouchers: tuple[str, ...] = field(default_factory=tuple)
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def key(self) -> str:
        """Stable identity of a listing across scans: Shopee needs both ids."""
        return f"{self.shop_id}_{self.item_id}"

    @property
    def url(self) -> str:
        """Canonical product URL (region-agnostic path form Shopee always accepts)."""
        return f"https://shopee.vn/product/{self.shop_id}/{self.item_id}"

    @property
    def rating_is_credible(self) -> bool:
        """A rating is only information once enough people have left one."""
        return self.rating is not None and self.rating_count >= 10

    def snapshot(self) -> PriceSnapshot:
        """The price-history row this observation contributes."""
        return PriceSnapshot(
            item_id=self.item_id,
            shop_id=self.shop_id,
            price=self.price,
            observed_at=self.captured_at,
            is_flash_sale=self.is_flash_sale,
        )


@dataclass(frozen=True, slots=True)
class PriceSnapshot:
    """One observed price for one listing at one time — the unit of price history."""

    item_id: int
    shop_id: int
    price: Money
    observed_at: datetime
    is_flash_sale: bool = False

    @property
    def key(self) -> str:
        return f"{self.shop_id}_{self.item_id}"


class Confidence(StrEnum):
    """How much observed history backs a verdict.

    NONE means we are quoting Shopee's own claim back at the user, which is exactly the
    situation the app exists to distrust — so the UI labels it.
    """

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DealFlag(StrEnum):
    """Machine-readable notes on a deal, rendered as badges and used by the notifier."""

    ALL_TIME_LOW = "all_time_low"
    CLAIM_INFLATED = "claim_inflated"
    FLASH_SALE = "flash_sale"
    PRICE_RISING = "price_rising"
    THIN_HISTORY = "thin_history"
    UNRATED_SELLER = "unrated_seller"
    FREE_SHIPPING = "free_shipping"


@dataclass(frozen=True, slots=True)
class Deal:
    """A verdict about one product: how real the discount is, and how good.

    Produced only by ``core.deals.evaluate``; the GUI and the notifier both consume it and
    neither recomputes any part of it.
    """

    product: Product
    reference_price: Money
    true_discount_pct: float
    score: float
    confidence: Confidence
    flags: frozenset[DealFlag] = frozenset()
    history_days: int = 0
    watch_id: Optional[str] = None

    @property
    def savings(self) -> Money:
        """Money saved against the reference price (never negative)."""
        delta = self.reference_price.amount - self.product.price.amount
        return Money(max(delta, 0), self.product.price.currency)

    @property
    def is_genuine(self) -> bool:
        """True when the drop is real: a measurable cut that history supports."""
        return (
            self.true_discount_pct >= 5.0
            and self.confidence is not Confidence.NONE
            and DealFlag.CLAIM_INFLATED not in self.flags
        )

    def with_watch(self, watch_id: str) -> Deal:
        return replace(self, watch_id=watch_id)


class SortOrder(StrEnum):
    """Search orderings Shopee's API supports (``by=`` parameter)."""

    RELEVANCE = "relevancy"
    LATEST = "ctime"
    TOP_SALES = "sales"
    PRICE_ASC = "price"
    PRICE_DESC = "price_desc"


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """What to ask a source for. Adapter-agnostic on purpose.

    ``limit`` is a *total* cap, not a page size: the adapter paginates up to it, and the
    default is deliberately small because this is a watcher, not a crawler.
    """

    keyword: str
    limit: int = 60
    order: SortOrder = SortOrder.RELEVANCE
    min_price: Optional[Money] = None
    max_price: Optional[Money] = None
    min_rating: Optional[float] = None
    category_id: Optional[int] = None
    shop_id: Optional[int] = None
    official_only: bool = False
    free_shipping_only: bool = False

    def __post_init__(self) -> None:
        if (
            not self.keyword.strip()
            and self.shop_id is None
            and self.category_id is None
        ):
            raise ValueError("a query needs a keyword, a shop_id, or a category_id")
        if self.limit <= 0:
            raise ValueError("limit must be positive")

    @property
    def page_count(self) -> int:
        """Pages of 60 needed to satisfy ``limit`` (Shopee's page size is fixed at 60)."""
        return max(1, math.ceil(self.limit / 60))


@dataclass(frozen=True, slots=True)
class Watch:
    """A standing instruction: "tell me when this kind of item drops".

    Matching lives in ``core.watchlist`` so this stays a plain description of intent.
    """

    watch_id: str
    keyword: str
    max_price: Optional[Money] = None
    min_discount_pct: float = 20.0
    min_rating: Optional[float] = 4.0
    min_sold: int = 0
    shop_id: Optional[int] = None
    exclude_terms: tuple[str, ...] = field(default_factory=tuple)
    official_only: bool = False
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_query(self, limit: int = 60) -> SearchQuery:
        """The search this watch implies."""
        return SearchQuery(
            keyword=self.keyword,
            limit=limit,
            order=SortOrder.RELEVANCE,
            max_price=self.max_price,
            min_rating=self.min_rating,
            shop_id=self.shop_id,
            official_only=self.official_only,
        )


def dedupe_products(products: Iterable[Product]) -> list[Product]:
    """Collapse duplicate listings, keeping the cheapest observation of each.

    Shopee returns the same item across pages and across keyword variants; scanning three
    watches for "tai nghe" must not report the same earbuds three times.
    """
    best: dict[str, Product] = {}
    for product in products:
        current = best.get(product.key)
        if current is None or product.price.amount < current.price.amount:
            best[product.key] = product
    return sorted(best.values(), key=lambda p: p.price.amount)
