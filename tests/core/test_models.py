"""Domain model invariants — mostly about money, because money bugs are silent."""

from __future__ import annotations

import pytest

from shopee_hunter.core.models import (
    SHOPEE_PRICE_SCALE,
    Currency,
    Money,
    SearchQuery,
    Shop,
    SortOrder,
    dedupe_products,
)


class TestMoney:
    def test_converts_shopees_scaled_integer(self):
        assert Money.from_shopee(12_900_000_000).amount == 129_000

    def test_scale_constant_matches_the_conversion(self):
        assert Money.from_shopee(SHOPEE_PRICE_SCALE).amount == 1

    @pytest.mark.parametrize("raw", [None, -1, -100_000])
    def test_missing_or_negative_prices_become_zero(self, raw):
        """Shopee uses -1 for an unavailable listing; it must not become a negative price."""
        assert Money.from_shopee(raw).is_zero

    def test_arithmetic_within_a_currency(self):
        assert Money(1_000) + Money(500) == Money(1_500)
        assert Money(1_000) - Money(500) == Money(500)

    def test_mixing_currencies_is_an_error(self):
        with pytest.raises(ValueError, match="cannot combine"):
            Money(1_000, Currency.VND) + Money(1, Currency.SGD)

    def test_is_ordered_so_a_list_of_prices_sorts(self):
        assert sorted([Money(300), Money(100), Money(200)]) == [
            Money(100),
            Money(200),
            Money(300),
        ]

    def test_amount_is_an_int_not_a_float(self):
        """A float price compounds rounding error through every discount calculation."""
        assert isinstance(Money.from_shopee(12_345_678).amount, int)


class TestShop:
    @pytest.mark.parametrize(
        ("official", "preferred", "level"),
        [(True, False, 2), (False, True, 1), (False, False, 0), (True, True, 2)],
    )
    def test_trust_level(self, official, preferred, level):
        assert (
            Shop(1, is_official=official, is_preferred=preferred).trust_level == level
        )


class TestProduct:
    def test_key_needs_both_ids(self, product_factory):
        product = product_factory(item_id=7, shop_id=9)
        assert product.key == "9_7"

    def test_url_is_the_canonical_product_path(self, product_factory):
        assert product_factory(item_id=7, shop_id=9).url.endswith("/product/9/7")

    def test_a_rating_from_three_people_is_not_credible(self, product_factory):
        assert not product_factory(rating=5.0, rating_count=3).rating_is_credible
        assert product_factory(rating=4.1, rating_count=50).rating_is_credible

    def test_snapshot_carries_the_observation_forward(self, product_factory):
        product = product_factory(price=123_000, flash=True)
        snapshot = product.snapshot()

        assert snapshot.price == product.price
        assert snapshot.observed_at == product.captured_at
        assert snapshot.is_flash_sale


class TestSearchQuery:
    def test_a_query_needs_something_to_search_by(self):
        with pytest.raises(ValueError, match="keyword"):
            SearchQuery("   ")

    def test_a_shop_id_alone_is_a_valid_query(self):
        assert SearchQuery("", shop_id=42).shop_id == 42

    def test_limit_must_be_positive(self):
        with pytest.raises(ValueError, match="limit"):
            SearchQuery("tai nghe", limit=0)

    @pytest.mark.parametrize(("limit", "pages"), [(1, 1), (60, 1), (61, 2), (180, 3)])
    def test_page_count_follows_shopees_fixed_page_size(self, limit, pages):
        assert SearchQuery("tai nghe", limit=limit).page_count == pages

    def test_sort_orders_are_shopees_own_vocabulary(self):
        assert SortOrder.TOP_SALES.value == "sales"


class TestDedupe:
    def test_keeps_the_cheapest_observation_of_each_listing(self, product_factory):
        products = [
            product_factory(item_id=1, price=300_000),
            product_factory(item_id=1, price=100_000),
            product_factory(item_id=2, price=200_000),
        ]

        unique = dedupe_products(products)

        assert [(p.item_id, p.price.amount) for p in unique] == [
            (1, 100_000),
            (2, 200_000),
        ]

    def test_result_is_sorted_by_price(self, product_factory):
        products = [
            product_factory(item_id=i, price=(5 - i) * 100_000) for i in range(1, 5)
        ]

        assert [p.price.amount for p in dedupe_products(products)] == [
            100_000,
            200_000,
            300_000,
            400_000,
        ]

    def test_empty_input_is_fine(self):
        assert dedupe_products([]) == []
