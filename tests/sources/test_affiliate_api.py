"""The affiliate adapter's wire mapping, and the failure modes it must not swallow.

Every test here is about the difference between "Shopee sent no claim" and "Shopee sent a
claim we cannot read". The first is ordinary; the second means the wire format moved, and
coercing it to a default is how a scraper reports "no deals" during a live sale while the
adapter is happily returning a full page of items (ADR-004, ADR-007).
"""

from __future__ import annotations

import pytest

from shopee_hunter.core.errors import ParseError
from shopee_hunter.sources.affiliate_api import AffiliateApiSource


def _node(**overrides: object) -> dict[str, object]:
    """A minimal well-formed affiliate node, with fields overridable per test."""
    node: dict[str, object] = {
        "itemId": 42,
        "shopId": 7,
        "productName": "Tai nghe Bluetooth",
        "price": 200_000,
        "priceDiscountRate": 25,
        "ratingStar": 4.5,
        "sales": 300,
        "imageUrl": "https://example.invalid/a.jpg",
        "shopName": "Shop",
        "shopType": [],
    }
    node.update(overrides)
    return node


@pytest.fixture
def source(settings) -> AffiliateApiSource:
    return AffiliateApiSource(settings)


class TestDiscountRate:
    def test_a_normal_rate_reconstructs_the_original_price(self, source):
        product = source._to_product(_node(price=75, priceDiscountRate=25))

        assert product.claimed_discount_pct == 25
        assert product.price_before_discount is not None
        assert product.price_before_discount.amount == 100

    @pytest.mark.parametrize("absent", [None, ""])
    def test_an_absent_rate_means_no_claim(self, source, absent):
        """Genuinely missing is not an error — plenty of listings claim nothing."""
        product = source._to_product(_node(priceDiscountRate=absent))

        assert product.claimed_discount_pct == 0
        assert product.price_before_discount is None

    @pytest.mark.parametrize("garbage", ["50%", "half off", {}, []])
    def test_an_unreadable_rate_raises_and_names_the_field(self, source, garbage):
        """Defaulting to 0 here disables the app's entire reason for existing.

        With `claimed_discount_pct == 0` on every item, CLAIM_INFLATED can never fire (there
        is no claim left to compare against) and `scan.min_discount_pct` filters the whole
        page away — so the UI says "no deals" while the wire is full of them, and nothing
        anywhere names the field that changed.
        """
        with pytest.raises(ParseError) as excinfo:
            source._to_product(_node(priceDiscountRate=garbage))

        assert "priceDiscountRate" in str(excinfo.value)


class TestRating:
    def test_a_missing_rating_is_none_not_zero(self, source):
        assert source._to_product(_node(ratingStar=None)).rating is None

    @pytest.mark.parametrize("garbage", ["4.5/5", {"value": 4.5}, []])
    def test_an_unreadable_rating_raises_a_typed_error(self, source, garbage):
        """A bare ValueError here escapes the seam entirely.

        `SourceChain` only catches `SourceError`, so an untyped exception skips the fallback
        to the next adapter and surfaces in the GUI as a traceback — where a `ParseError`
        would have been logged and the web source tried instead.
        """
        with pytest.raises(ParseError) as excinfo:
            source._to_product(_node(ratingStar=garbage))

        assert "ratingStar" in str(excinfo.value)


class TestIdentity:
    def test_a_missing_identity_field_is_still_a_parse_error(self, source):
        node = _node()
        del node["itemId"]

        with pytest.raises(ParseError):
            source._to_product(node)
