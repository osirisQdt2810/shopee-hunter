"""The deal engine: is this discount real, and is it any good?

The one rule that shapes this module: **Shopee's own discount percentage is a marketing
claim, not a measurement.** A listing permanently tagged "-50%" against a
``price_before_discount`` nobody ever paid is the single most common thing a naive price
watcher reports. So the reference price is derived from *observed* history, and the claim
is only a fallback — one the verdict labels as unverified.

Pure functions over ``core.models``: no clock of its own, no I/O, no Qt.
"""

from __future__ import annotations

import itertools
import statistics
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Optional

from .models import (
    Confidence,
    Deal,
    DealFlag,
    Money,
    PriceSnapshot,
    Product,
)

# History older than this says nothing about today's price on a fast-moving marketplace.
DEFAULT_LOOKBACK_DAYS = 90

# Below this many observations, the median is a coincidence rather than a baseline.
_MEDIUM_CONFIDENCE_SAMPLES = 5
_HIGH_CONFIDENCE_SAMPLES = 12
_HIGH_CONFIDENCE_DAYS = 21

# Shopee claims a discount this many points larger than the observed one → the claim is
# inflated. 15 points of slack absorbs honest rounding and short-lived voucher pricing.
CLAIM_INFLATION_TOLERANCE_PCT = 15.0

# Discount below this is noise, not an event worth waking a user for.
MIN_INTERESTING_DISCOUNT_PCT = 5.0


def _within_lookback(
    history: Iterable[PriceSnapshot], now: datetime, lookback_days: int
) -> list[PriceSnapshot]:
    cutoff = now - timedelta(days=lookback_days)
    return [snap for snap in history if snap.observed_at >= cutoff]


def reference_price(
    product: Product,
    history: Sequence[PriceSnapshot],
    *,
    now: Optional[datetime] = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> tuple[Money, Confidence, int]:
    """The price this listing "normally" sells at.

    Uses the median of observed non-flash prices — median, not mean, because one 24-hour
    flash price must not drag the baseline down and make every later day look like a deal.
    Flash-sale observations are excluded for the same reason; if *all* we have is flash
    prices, they are used rather than throwing the history away.

    Args:
        product: The listing being judged (its current price is never part of the baseline).
        history: Past observations of the same listing, any order.
        now: Reference instant; defaults to the product's capture time so a replayed
            fixture evaluates identically today and next year.
        lookback_days: How far back history stays relevant.

    Returns:
        ``(reference, confidence, days_of_history)``. When there is no usable history the
        reference falls back to Shopee's claimed original price with ``Confidence.NONE``,
        and to the current price (i.e. "no discount") if there is not even a claim.
    """
    moment = now or product.captured_at
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)

    relevant = _within_lookback(history, moment, lookback_days)
    steady = [snap for snap in relevant if not snap.is_flash_sale] or relevant

    if not steady:
        claimed = product.price_before_discount
        if claimed is not None and claimed.amount > product.price.amount:
            return claimed, Confidence.NONE, 0
        return product.price, Confidence.NONE, 0

    span_days = (moment - min(snap.observed_at for snap in steady)).days
    median = int(statistics.median(snap.price.amount for snap in steady))

    if len(steady) >= _HIGH_CONFIDENCE_SAMPLES and span_days >= _HIGH_CONFIDENCE_DAYS:
        confidence = Confidence.HIGH
    elif len(steady) >= _MEDIUM_CONFIDENCE_SAMPLES:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW

    return Money(median, product.price.currency), confidence, span_days


def discount_pct(current: Money, reference: Money) -> float:
    """Percentage drop from ``reference`` to ``current``; 0.0 when there is no drop."""
    if reference.amount <= 0 or current.amount >= reference.amount:
        return 0.0
    return (reference.amount - current.amount) / reference.amount * 100.0


def _collect_flags(
    product: Product,
    history: Sequence[PriceSnapshot],
    true_pct: float,
    confidence: Confidence,
) -> frozenset[DealFlag]:
    flags: set[DealFlag] = set()

    if product.is_flash_sale:
        flags.add(DealFlag.FLASH_SALE)
    if product.has_free_shipping:
        flags.add(DealFlag.FREE_SHIPPING)
    if not product.rating_is_credible:
        flags.add(DealFlag.UNRATED_SELLER)
    if confidence in (Confidence.NONE, Confidence.LOW):
        flags.add(DealFlag.THIN_HISTORY)

    if product.claimed_discount_pct - true_pct > CLAIM_INFLATION_TOLERANCE_PCT:
        flags.add(DealFlag.CLAIM_INFLATED)

    if history:
        lowest = min(snap.price.amount for snap in history)
        if product.price.amount <= lowest:
            flags.add(DealFlag.ALL_TIME_LOW)
        recent = sorted(history, key=lambda snap: snap.observed_at)[-3:]
        if len(recent) == 3 and all(
            earlier.price.amount < later.price.amount
            for earlier, later in itertools.pairwise(recent)
        ):
            flags.add(DealFlag.PRICE_RISING)

    return frozenset(flags)


# Score weights. Discount size dominates, but a big drop on an unverifiable listing from
# an unrated seller must not outrank a solid one — hence the multiplicative penalties.
_CONFIDENCE_WEIGHT: dict[Confidence, float] = {
    Confidence.NONE: 0.45,
    Confidence.LOW: 0.7,
    Confidence.MEDIUM: 0.9,
    Confidence.HIGH: 1.0,
}


def score_deal(
    product: Product,
    true_pct: float,
    confidence: Confidence,
    flags: frozenset[DealFlag],
) -> float:
    """Rank a deal 0–100. Comparable across watches, so one list can be sorted.

    Composition: the discount carries the score (a 60% drop scores far above a 10% one, but
    with diminishing returns above ~60% because that range is where fake listings live),
    then evidence quality scales it, then credibility signals adjust it.
    """
    # 0–70 points from the discount, saturating: 20% → ~33, 40% → ~52, 60% → ~63.
    discount_points = 70.0 * (1.0 - 0.97 ** max(true_pct, 0.0))

    trust_points = 0.0
    if product.shop is not None:
        trust_points += product.shop.trust_level * 4.0
    if product.rating_is_credible and product.rating is not None:
        trust_points += max(0.0, (product.rating - 3.5) / 1.5) * 8.0
    if product.sold_count >= 100:
        trust_points += 4.0
    if DealFlag.ALL_TIME_LOW in flags:
        trust_points += 10.0
    if DealFlag.FREE_SHIPPING in flags:
        trust_points += 2.0

    penalty = 0.0
    if DealFlag.CLAIM_INFLATED in flags:
        penalty += 12.0
    if DealFlag.UNRATED_SELLER in flags:
        penalty += 6.0
    if DealFlag.PRICE_RISING in flags:
        penalty += 4.0

    raw = (discount_points + trust_points) * _CONFIDENCE_WEIGHT[confidence] - penalty
    return round(min(100.0, max(0.0, raw)), 1)


def evaluate(
    product: Product,
    history: Sequence[PriceSnapshot] = (),
    *,
    now: Optional[datetime] = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> Deal:
    """Turn one observation plus its history into a ranked verdict.

    This is the only place a ``Deal`` is created. Callers that want to filter should use
    ``Deal.is_genuine`` / ``Deal.score`` rather than re-deriving anything.
    """
    reference, confidence, history_days = reference_price(
        product, history, now=now, lookback_days=lookback_days
    )
    true_pct = round(discount_pct(product.price, reference), 2)
    flags = _collect_flags(product, history, true_pct, confidence)
    return Deal(
        product=product,
        reference_price=reference,
        true_discount_pct=true_pct,
        score=score_deal(product, true_pct, confidence, flags),
        confidence=confidence,
        flags=flags,
        history_days=history_days,
    )


def rank_deals(
    products: Iterable[Product],
    history_by_key: Optional[dict[str, Sequence[PriceSnapshot]]] = None,
    *,
    now: Optional[datetime] = None,
    min_discount_pct: float = MIN_INTERESTING_DISCOUNT_PCT,
    genuine_only: bool = False,
) -> list[Deal]:
    """Evaluate many products and return them best-first.

    Args:
        products: Observations from a scan (already deduped by ``dedupe_products``).
        history_by_key: Past snapshots keyed by ``Product.key``.
        now: Reference instant for lookback maths.
        min_discount_pct: Drop everything below this observed discount.
        genuine_only: Also drop anything ``Deal.is_genuine`` rejects.

    Returns:
        Deals sorted by score descending, then by savings descending.
    """
    history_by_key = history_by_key or {}
    deals: list[Deal] = []
    for product in products:
        deal = evaluate(product, history_by_key.get(product.key, ()), now=now)
        if deal.true_discount_pct < min_discount_pct:
            continue
        if genuine_only and not deal.is_genuine:
            continue
        deals.append(deal)
    return sorted(deals, key=lambda d: (-d.score, -d.savings.amount))
