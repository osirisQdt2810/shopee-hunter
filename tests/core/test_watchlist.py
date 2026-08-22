"""Watch matching, including the Vietnamese-text behaviour the market requires."""

from __future__ import annotations

import pytest

from shopee_hunter.core.models import Money, Watch
from shopee_hunter.core.watchlist import (
    assign_deals,
    deal_matches,
    excluded,
    keyword_matches,
    normalise,
    product_matches,
)


class TestNormalise:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Tai Nghe Bluetooth", "tai nghe bluetooth"),
            ("Ốp Lưng", "op lung"),
            ("Đèn LED", "den led"),
            ("CƯỜNG LỰC", "cuong luc"),
            ("Nồi chiên không dầu", "noi chien khong dau"),
        ],
    )
    def test_strips_diacritics_and_case(self, text, expected):
        assert normalise(text) == expected


class TestKeywordMatching:
    def test_all_tokens_must_appear_but_order_does_not_matter(self):
        assert keyword_matches("Bluetooth Tai Nghe Pro", "tai nghe bluetooth")
        assert not keyword_matches("Tai Nghe Pro", "tai nghe bluetooth")

    def test_matches_across_diacritics_in_both_directions(self):
        assert keyword_matches("TAI NGHÉ khong day", "tai nghe")
        assert keyword_matches("tai nghe khong day", "TAI NGHE")

    def test_an_empty_keyword_matches_everything(self):
        assert keyword_matches("anything at all", "")

    def test_exclusions_are_diacritic_insensitive(self):
        assert excluded("Ốp lưng iPhone 15", ["op lung"])
        assert not excluded("Tai nghe", ["op lung"])

    def test_blank_exclusion_terms_are_ignored(self):
        assert not excluded("Tai nghe", ["   ", ""])


class TestProductMatches:
    def test_price_ceiling(self, product_factory):
        product = product_factory(price=450_000)

        assert product_matches(
            product, Watch("w", "tai nghe", max_price=Money(500_000))
        )
        assert not product_matches(
            product, Watch("w", "tai nghe", max_price=Money(400_000))
        )

    def test_an_unrated_listing_fails_a_rating_floor(self, product_factory):
        """ "At least 4 stars" cannot honestly include "no stars yet"."""
        product = product_factory(rating=5.0, rating_count=2)

        assert not product_matches(product, Watch("w", "tai nghe", min_rating=4.0))

    def test_no_rating_floor_lets_an_unrated_listing_through(self, product_factory):
        product = product_factory(rating=None, rating_count=0)

        assert product_matches(product, Watch("w", "tai nghe", min_rating=None))

    def test_official_only(self, product_factory):
        watch = Watch("w", "tai nghe", official_only=True, min_rating=None)

        assert product_matches(product_factory(official=True), watch)
        assert not product_matches(product_factory(official=False), watch)

    def test_shop_filter(self, product_factory):
        watch = Watch("w", "tai nghe", shop_id=999, min_rating=None)

        assert not product_matches(product_factory(shop_id=100), watch)
        assert product_matches(product_factory(shop_id=999), watch)

    def test_minimum_sold_count(self, product_factory):
        watch = Watch("w", "tai nghe", min_sold=500, min_rating=None)

        assert product_matches(product_factory(sold=1_000), watch)
        assert not product_matches(product_factory(sold=10), watch)

    def test_exclusions_win_over_a_keyword_match(self, product_factory):
        product = product_factory(name="Tai nghe kèm ốp lưng")
        watch = Watch("w", "tai nghe", exclude_terms=("op lung",), min_rating=None)

        assert not product_matches(product, watch)


class TestDealMatching:
    def test_the_discount_threshold_uses_the_observed_discount(
        self, product_factory, snapshot_factory, now
    ):
        from shopee_hunter.core.deals import evaluate

        # Shopee claims 50% off; observed history says 20%.
        product = product_factory(price=200_000, before=400_000, claimed=50)
        deal = evaluate(product, snapshot_factory(250_000, count=14), now=now)

        assert deal_matches(
            deal, Watch("w", "tai nghe", min_discount_pct=15.0, min_rating=None)
        )
        assert not deal_matches(
            deal, Watch("w", "tai nghe", min_discount_pct=45.0, min_rating=None)
        )

    def test_assign_tags_the_first_matching_watch_only(
        self, product_factory, snapshot_factory, now
    ):
        from shopee_hunter.core.deals import evaluate

        deal = evaluate(
            product_factory(price=100_000, before=None),
            snapshot_factory(200_000),
            now=now,
        )
        watches = [
            Watch("first", "tai nghe", min_discount_pct=5.0, min_rating=None),
            Watch("second", "tai nghe", min_discount_pct=5.0, min_rating=None),
        ]

        tagged = assign_deals([deal], watches)

        assert len(tagged) == 1
        assert tagged[0].watch_id == "first"

    def test_unmatched_deals_are_dropped(self, product_factory, snapshot_factory, now):
        from shopee_hunter.core.deals import evaluate

        deal = evaluate(
            product_factory(name="Bàn phím cơ", price=100_000, before=None),
            snapshot_factory(200_000),
            now=now,
        )

        assert assign_deals([deal], [Watch("w", "tai nghe", min_rating=None)]) == []

    def test_disabled_watches_do_not_match(
        self, product_factory, snapshot_factory, now
    ):
        from shopee_hunter.core.deals import evaluate

        deal = evaluate(
            product_factory(price=100_000, before=None),
            snapshot_factory(200_000),
            now=now,
        )

        assert (
            assign_deals(
                [deal], [Watch("w", "tai nghe", enabled=False, min_rating=None)]
            )
            == []
        )
