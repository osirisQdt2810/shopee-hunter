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


class TestPageTolerance:
    """One bad node must not cost the whole page — the policy `parse_search_response` states.

    Raising `ParseError` from `_to_product` was the right call for a field that changed
    shape, but letting it abort `_do_search` would have replaced a silent wrong answer with a
    loud total failure: fifty good listings discarded because one was odd. The shared parser
    already resolves this exact tension ("one malformed listing among sixty should not cost
    the user the other fifty-nine"), and this adapter has to resolve it the same way.
    """

    @staticmethod
    def _page(nodes: list[dict], has_next: bool = False) -> dict:
        return {
            "productOfferV2": {"nodes": nodes, "pageInfo": {"hasNextPage": has_next}}
        }

    async def test_a_single_bad_node_is_skipped(self, source, monkeypatch):
        from shopee_hunter.core.models import SearchQuery

        page = self._page(
            [_node(itemId=1), _node(itemId=2, ratingStar="4.5/5"), _node(itemId=3)]
        )

        async def fake_post(query, variables):
            return page

        monkeypatch.setattr(source, "_post", fake_post)

        products = await source._do_search(SearchQuery("tai nghe", limit=10))

        assert [p.item_id for p in products] == [1, 3]

    async def test_a_page_where_nothing_parses_raises(self, source, monkeypatch):
        """Every node failing is not one odd listing, it is the wire format moving."""
        from shopee_hunter.core.models import SearchQuery

        page = self._page(
            [_node(itemId=1, ratingStar="4.5/5"), _node(itemId=2, ratingStar="4.5/5")]
        )

        async def fake_post(query, variables):
            return page

        monkeypatch.setattr(source, "_post", fake_post)

        with pytest.raises(ParseError, match="none of 2"):
            await source._do_search(SearchQuery("tai nghe", limit=10))

    async def test_an_empty_page_is_not_an_error(self, source, monkeypatch):
        from shopee_hunter.core.models import SearchQuery

        async def fake_post(query, variables):
            return self._page([])

        monkeypatch.setattr(source, "_post", fake_post)

        assert await source._do_search(SearchQuery("tai nghe", limit=10)) == []


class TestNumericEdgeCases:
    @pytest.mark.parametrize("value", ["inf", "-inf", "1e400"])
    def test_an_infinite_rate_raises_rather_than_overflowing(self, source, value):
        """`int(float("inf"))` raises OverflowError, which is not a ValueError."""
        with pytest.raises(ParseError, match="priceDiscountRate"):
            source._to_product(_node(priceDiscountRate=value))

    @pytest.mark.parametrize("value", ["nan", "inf", "1e400"])
    def test_a_non_finite_rating_raises(self, source, value):
        """`float("nan")` succeeds, and a NaN silently answers False to every comparison."""
        with pytest.raises(ParseError, match="ratingStar"):
            source._to_product(_node(ratingStar=value))

    def test_an_unreadable_sold_count_raises_rather_than_escaping_untyped(self, source):
        """The third instance of the swallow-and-default shape, three lines from the others."""
        with pytest.raises(ParseError, match="sales"):
            source._to_product(_node(sales="2.5k"))


class TestSigning:
    """The signature is the whole auth story for this transport, and had no coverage."""

    @pytest.fixture
    def signed(self, settings):
        settings.sources.affiliate.app_id = "app-123"
        settings.sources.affiliate.app_secret = "s3cr3t"
        return AffiliateApiSource(settings)

    def test_the_header_carries_credential_timestamp_and_signature(self, signed):
        header = signed._sign('{"query":"x"}', 1_700_000_000)

        assert header.startswith("SHA256 Credential=app-123,")
        assert "Timestamp=1700000000" in header
        assert "Signature=" in header

    def test_the_secret_itself_never_appears_in_the_header(self, signed):
        """It is hashed into the signature, not sent — a header lands in logs and bug reports."""
        assert "s3cr3t" not in signed._sign('{"query":"x"}', 1_700_000_000)

    def test_the_signature_covers_the_timestamp(self, signed):
        """Which is why a wrong system clock shows up as an auth failure, not a network one."""
        payload = '{"query":"x"}'

        assert signed._sign(payload, 1_700_000_000) != signed._sign(
            payload, 1_700_000_001
        )

    def test_the_signature_covers_the_payload(self, signed):
        assert signed._sign('{"a":1}', 1_700_000_000) != signed._sign(
            '{"a":2}', 1_700_000_000
        )

    async def test_missing_credentials_raise_before_any_request(self, settings):
        """`SourceAuthRequired`, not a 401 round-trip — waiting cannot fix a missing key."""
        from shopee_hunter.core.errors import SourceAuthRequired

        settings.sources.affiliate.app_id = ""
        settings.sources.affiliate.app_secret = ""

        with pytest.raises(SourceAuthRequired):
            await AffiliateApiSource(settings)._post("query", {})
