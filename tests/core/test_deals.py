"""The deal engine. These tests are the specification of ADR-005.

The cases below are the app's whole reason to exist, so they are written as statements about
behaviour a user would notice, not as coverage of branches.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from shopee_hunter.core.deals import (
    CLAIM_INFLATION_TOLERANCE_PCT,
    discount_pct,
    evaluate,
    rank_deals,
    reference_price,
    score_deal,
)
from shopee_hunter.core.models import Confidence, DealFlag, Money, PriceSnapshot


class TestReferencePrice:
    def test_no_history_falls_back_to_the_claim_but_marks_it_unverified(
        self, product_factory, now
    ):
        product = product_factory(price=200_000, before=400_000)

        reference, confidence, days = reference_price(product, [], now=now)

        assert reference == Money(400_000)
        # The important half: we quoted Shopee's claim, and we said so.
        assert confidence is Confidence.NONE
        assert days == 0

    def test_no_history_and_no_claim_means_no_discount(self, product_factory, now):
        product = product_factory(price=200_000, before=None)

        reference, confidence, _ = reference_price(product, [], now=now)

        assert reference == product.price
        assert confidence is Confidence.NONE

    def test_uses_the_median_of_observed_prices(
        self, product_factory, snapshot_factory, now
    ):
        product = product_factory(price=100_000)
        history = snapshot_factory(300_000, count=6) + snapshot_factory(
            500_000, count=1
        )

        reference, _, _ = reference_price(product, history, now=now)

        # Median, not mean: the single 500k observation must not drag the baseline up.
        assert reference == Money(300_000)

    def test_one_flash_price_cannot_define_the_baseline(
        self, product_factory, snapshot_factory, now
    ):
        product = product_factory(price=100_000)
        steady = snapshot_factory(300_000, count=8)
        flash = snapshot_factory(90_000, count=3, flash=True)

        reference, _, _ = reference_price(product, steady + flash, now=now)

        assert reference == Money(
            300_000
        ), "flash observations must be excluded from the baseline"

    def test_flash_only_history_is_used_rather_than_discarded(
        self, product_factory, snapshot_factory, now
    ):
        product = product_factory(price=100_000)
        flash_only = snapshot_factory(250_000, count=6, flash=True)

        reference, confidence, _ = reference_price(product, flash_only, now=now)

        assert reference == Money(250_000)
        assert confidence is not Confidence.NONE

    def test_history_outside_the_lookback_window_is_ignored(
        self, product_factory, snapshot_factory, now
    ):
        product = product_factory(price=100_000, before=None)
        ancient = [
            PriceSnapshot(
                item_id=1,
                shop_id=100,
                price=Money(900_000),
                observed_at=now - timedelta(days=400),
            )
        ]

        reference, confidence, _ = reference_price(
            product, ancient, now=now, lookback_days=90
        )

        assert reference == product.price
        assert confidence is Confidence.NONE

    @pytest.mark.parametrize(
        ("count", "every_days", "expected"),
        [
            (2, 3, Confidence.LOW),
            (6, 2, Confidence.MEDIUM),
            (14, 5, Confidence.HIGH),
        ],
    )
    def test_confidence_grows_with_the_evidence(
        self, product_factory, snapshot_factory, now, count, every_days, expected
    ):
        product = product_factory(price=100_000)
        history = snapshot_factory(200_000, count=count, every_days=every_days)

        _, confidence, _ = reference_price(product, history, now=now)

        assert confidence is expected


class TestDiscount:
    def test_a_price_above_the_reference_is_not_a_discount(self):
        assert discount_pct(Money(300_000), Money(200_000)) == 0.0

    def test_zero_reference_cannot_produce_a_hundred_percent_off(self):
        assert discount_pct(Money(0), Money(0)) == 0.0

    def test_ordinary_drop(self):
        assert discount_pct(Money(150_000), Money(200_000)) == pytest.approx(25.0)


class TestEvaluate:
    def test_a_verified_drop_is_genuine(self, product_factory, snapshot_factory, now):
        product = product_factory(price=200_000, before=400_000, claimed=50)
        history = snapshot_factory(390_000, count=14, every_days=5)

        deal = evaluate(product, history, now=now)

        assert deal.confidence is Confidence.HIGH
        assert deal.true_discount_pct == pytest.approx(48.7, abs=0.2)
        assert deal.is_genuine
        assert DealFlag.CLAIM_INFLATED not in deal.flags

    def test_an_inflated_claim_is_flagged_and_not_genuine(
        self, product_factory, snapshot_factory, now
    ):
        # Shopee says -50%; the listing has actually sold at this price all along.
        product = product_factory(price=200_000, before=400_000, claimed=50)
        history = snapshot_factory(205_000, count=14, every_days=5)

        deal = evaluate(product, history, now=now)

        assert DealFlag.CLAIM_INFLATED in deal.flags
        assert not deal.is_genuine
        assert (
            deal.product.claimed_discount_pct - deal.true_discount_pct
            > CLAIM_INFLATION_TOLERANCE_PCT
        )

    def test_no_history_is_never_genuine_however_large_the_claim(
        self, product_factory, now
    ):
        product = product_factory(price=10_000, before=1_000_000, claimed=99)

        deal = evaluate(product, [], now=now)

        assert deal.true_discount_pct == pytest.approx(99.0)
        assert deal.confidence is Confidence.NONE
        assert (
            not deal.is_genuine
        ), "an unverifiable 99% off is exactly what must not be recommended"

    def test_all_time_low_is_flagged(self, product_factory, snapshot_factory, now):
        product = product_factory(price=100_000, before=None)
        history = snapshot_factory(300_000, count=10)

        deal = evaluate(product, history, now=now)

        assert DealFlag.ALL_TIME_LOW in deal.flags

    def test_a_rising_price_is_flagged(self, product_factory, now):
        product = product_factory(price=250_000, before=None)
        rising = [
            PriceSnapshot(
                item_id=1,
                shop_id=100,
                price=Money(price),
                observed_at=now - timedelta(days=days),
            )
            for price, days in ((300_000, 9), (320_000, 6), (340_000, 3))
        ]

        deal = evaluate(product, rising, now=now)

        assert DealFlag.PRICE_RISING in deal.flags

    def test_an_unrated_seller_is_flagged(self, product_factory, snapshot_factory, now):
        product = product_factory(price=100_000, rating=5.0, rating_count=3)

        deal = evaluate(product, snapshot_factory(200_000), now=now)

        assert DealFlag.UNRATED_SELLER in deal.flags

    def test_savings_never_goes_negative(self, product_factory, snapshot_factory, now):
        product = product_factory(price=400_000, before=None)
        deal = evaluate(product, snapshot_factory(200_000), now=now)

        assert deal.savings.amount == 0


class TestScore:
    def test_bigger_verified_discounts_score_higher(self, product_factory):
        modest = score_deal(product_factory(), 15.0, Confidence.HIGH, frozenset())
        deep = score_deal(product_factory(), 45.0, Confidence.HIGH, frozenset())

        assert deep > modest

    def test_thin_evidence_lowers_the_score_for_the_same_discount(
        self, product_factory
    ):
        verified = score_deal(product_factory(), 40.0, Confidence.HIGH, frozenset())
        unverified = score_deal(product_factory(), 40.0, Confidence.NONE, frozenset())

        assert unverified < verified

    def test_an_inflated_claim_is_penalised(self, product_factory):
        clean = score_deal(product_factory(), 30.0, Confidence.HIGH, frozenset())
        inflated = score_deal(
            product_factory(),
            30.0,
            Confidence.HIGH,
            frozenset({DealFlag.CLAIM_INFLATED}),
        )

        assert inflated < clean

    def test_score_is_bounded(self, product_factory):
        assert (
            0.0
            <= score_deal(product_factory(), 99.0, Confidence.HIGH, frozenset())
            <= 100.0
        )
        assert (
            0.0
            <= score_deal(
                product_factory(rating=None, rating_count=0, official=False),
                1.0,
                Confidence.NONE,
                frozenset({DealFlag.CLAIM_INFLATED, DealFlag.UNRATED_SELLER}),
            )
            <= 100.0
        )


class TestRankDeals:
    def test_orders_best_first_and_applies_the_threshold(
        self, product_factory, snapshot_factory, now
    ):
        small = product_factory(item_id=1, price=190_000, before=None)
        large = product_factory(item_id=2, price=100_000, before=None)
        history = {
            "100_1": snapshot_factory(200_000, item_id=1),
            "100_2": snapshot_factory(400_000, item_id=2),
        }

        deals = rank_deals([small, large], history, now=now, min_discount_pct=10.0)

        assert [deal.product.item_id for deal in deals] == [2]

    def test_genuine_only_drops_unverifiable_deals(self, product_factory, now):
        product = product_factory(price=10_000, before=500_000, claimed=98)

        assert rank_deals([product], {}, now=now, min_discount_pct=5.0) != []
        assert (
            rank_deals([product], {}, now=now, min_discount_pct=5.0, genuine_only=True)
            == []
        )
