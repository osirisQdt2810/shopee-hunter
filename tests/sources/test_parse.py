"""Wire-format parsing.

Two kinds of case here, and the difference matters (ADR-008):

* **synthetic payloads** — built inline, clearly labelled, pinning the *rules* (the ×100_000
  scale, the rating histogram, the `error: 10` classification). They are the specification.
* **the captured fixture** — a real response, skipped when absent. It is the only thing that
  can tell us Shopee changed something, and it cannot be replaced by a payload we wrote.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from shopee_hunter.core.errors import ParseError, SourceBlocked
from shopee_hunter.core.models import Currency
from shopee_hunter.sources.parse import (
    IMAGE_CDN,
    check_api_error,
    parse_flash_sale_response,
    parse_item,
    parse_search_response,
)

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "shopee_web"
    / "search_items.json"
)


def item_basic(**overrides: Any) -> dict[str, Any]:
    """A SYNTHETIC search hit. Shaped like the real thing; not a substitute for a capture."""
    payload: dict[str, Any] = {
        "itemid": 111,
        "shopid": 222,
        "name": "Tai nghe Bluetooth ABC",
        "price": 19_900_000_000,
        "price_before_discount": 49_900_000_000,
        "raw_discount": 60,
        "item_rating": {"rating_star": 4.72, "rating_count": [812, 5, 7, 20, 100, 680]},
        "historical_sold": 1_234,
        "stock": 42,
        "image": "abc123hash",
        "shop_location": "Hà Nội",
        "is_official_shop": True,
        "show_free_shipping": True,
    }
    payload.update(overrides)
    return {"item_basic": payload}


class TestParseItem:
    def test_prices_come_off_the_wire_scale(self):
        product = parse_item(item_basic())

        assert product.price.amount == 199_000
        assert product.price_before_discount is not None
        assert product.price_before_discount.amount == 499_000

    def test_the_claimed_discount_is_parsed_but_stays_a_claim(self):
        product = parse_item(item_basic(raw_discount=60))

        assert product.claimed_discount_pct == 60

    @pytest.mark.parametrize("claimed", [-5, 150])
    def test_an_impossible_claim_is_clamped(self, claimed):
        assert (
            0
            <= parse_item(item_basic(raw_discount=claimed)).claimed_discount_pct
            <= 100
        )

    def test_rating_count_is_the_histogram_total(self):
        product = parse_item(item_basic())

        assert product.rating == pytest.approx(4.72)
        assert product.rating_count == 812

    def test_a_scalar_rating_count_still_works(self):
        product = parse_item(
            item_basic(item_rating={"rating_star": 4.0, "rating_count": 17})
        )

        assert product.rating_count == 17

    def test_a_missing_rating_block_is_not_fatal(self):
        product = parse_item(item_basic(item_rating=None))

        assert product.rating is None
        assert product.rating_count == 0

    def test_an_undiscounted_listing_has_no_original_price(self):
        """Shopee sets price_before_discount to 0 (or below price) when nothing is off."""
        assert (
            parse_item(item_basic(price_before_discount=0)).price_before_discount
            is None
        )
        assert (
            parse_item(
                item_basic(price_before_discount=1_000_000_000)
            ).price_before_discount
            is None
        )

    def test_images_get_the_cdn_prefix(self):
        assert parse_item(item_basic()).image_url == f"{IMAGE_CDN}abc123hash"

    def test_falls_back_to_the_images_array(self):
        product = parse_item(item_basic(image="", images=["fromarray"]))

        assert product.image_url.endswith("fromarray")

    def test_no_image_is_an_empty_string_not_a_broken_url(self):
        assert parse_item(item_basic(image="", images=[])).image_url == ""

    def test_flash_sale_stock_marks_the_listing(self):
        assert parse_item(item_basic(flash_sale_stock=10)).is_flash_sale
        assert not parse_item(item_basic()).is_flash_sale

    def test_official_shop_and_verified_both_mean_official(self):
        assert parse_item(
            item_basic(is_official_shop=False, shopee_verified=True)
        ).shop.is_official

    def test_a_bare_item_payload_needs_no_item_basic_wrapper(self):
        assert parse_item(item_basic()["item_basic"]).item_id == 111

    def test_currency_is_carried_through(self):
        product = parse_item(item_basic(), currency=Currency.SGD)

        assert product.price.currency is Currency.SGD

    @pytest.mark.parametrize("missing", ["itemid", "shopid", "price"])
    def test_a_missing_essential_field_names_itself(self, missing):
        payload = item_basic()
        del payload["item_basic"][missing]

        with pytest.raises(ParseError, match=missing):
            parse_item(payload)

    def test_a_nameless_listing_is_rejected(self):
        with pytest.raises(ParseError, match="no name"):
            parse_item(item_basic(name="   "))

    def test_a_non_numeric_price_is_a_parse_error_not_a_zero(self):
        with pytest.raises(ParseError):
            parse_item(item_basic(price="ten thousand"))


class TestApiError:
    @pytest.mark.parametrize("code", [10, 99])
    def test_the_anti_bot_codes_are_blocking_not_parse_failures(self, code):
        """`error: 10` arrives with HTTP 200. Treating it as "no results" is the bug."""
        with pytest.raises(SourceBlocked, match="refused"):
            check_api_error({"error": code, "error_msg": "server busy"}, source="web")

    @pytest.mark.parametrize("payload", [{}, {"error": None}, {"error": 0}])
    def test_a_healthy_body_passes(self, payload):
        check_api_error(payload, source="web")

    def test_an_unrecognised_error_code_is_a_parse_error(self):
        with pytest.raises(ParseError, match="777"):
            check_api_error({"error": 777, "error_msg": "who knows"}, source="web")


class TestParseSearchResponse:
    def test_parses_a_page(self):
        products = parse_search_response(
            {"error": None, "items": [item_basic(), item_basic(itemid=333)]}
        )

        assert [p.item_id for p in products] == [111, 333]

    def test_a_genuinely_empty_result_is_an_empty_list(self):
        assert parse_search_response({"error": None, "items": []}) == []

    def test_one_bad_entry_does_not_cost_the_rest_of_the_page(self):
        body = {
            "error": None,
            "items": [
                item_basic(),
                {"item_basic": {"name": "broken"}},
                item_basic(itemid=444),
            ],
        }

        products = parse_search_response(body)

        assert [p.item_id for p in products] == [111, 444]

    def test_a_page_where_nothing_parses_is_a_wire_format_change(self):
        with pytest.raises(ParseError, match="none of"):
            parse_search_response(
                {"error": None, "items": [{"item_basic": {"name": "x"}}]}
            )

    def test_a_body_with_no_items_key_is_a_parse_error(self):
        with pytest.raises(ParseError, match="items"):
            parse_search_response({"error": None})

    def test_a_blocking_error_takes_priority_over_the_items(self):
        with pytest.raises(SourceBlocked):
            parse_search_response({"error": 10, "items": [item_basic()]})


class TestParseFlashSale:
    def test_reads_the_nested_data_items(self):
        products = parse_flash_sale_response(
            {"error": None, "data": {"items": [item_basic()["item_basic"]]}}
        )

        assert len(products) == 1

    def test_every_flash_entry_is_marked_flash(self):
        """The endpoint guarantees it even when the payload does not say so."""
        products = parse_flash_sale_response(
            {"error": None, "data": {"items": [item_basic()["item_basic"]]}}
        )

        assert products[0].is_flash_sale

    def test_accepts_a_top_level_items_list_too(self):
        products = parse_flash_sale_response(
            {"error": None, "items": [item_basic()["item_basic"]]}
        )

        assert len(products) == 1


@pytest.mark.skipif(
    not FIXTURE.is_file(),
    reason="no captured fixture yet — see tests/fixtures/README.md",
)
class TestCapturedFixture:
    """The only tests that can notice Shopee changing its wire format."""

    @pytest.fixture
    def body(self) -> dict[str, Any]:
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_the_capture_still_parses(self, body):
        products = parse_search_response(body, source="fixture")

        assert (
            products
        ), "the captured response parsed to zero products — the format moved"

    def test_every_parsed_product_is_usable(self, body):
        for product in parse_search_response(body, source="fixture"):
            assert product.name
            assert product.item_id > 0
            assert product.shop_id > 0
            assert product.price.amount >= 0
            assert 0 <= product.claimed_discount_pct <= 100

    def test_the_capture_carries_no_session_data(self, body):
        """capture_fixture.py strips these; a hand-added capture might not have."""
        forbidden = {"userid", "user_id", "session_id", "tracking_info"}
        assert not (
            forbidden & set(body)
        ), f"committed fixture contains session keys: {forbidden & set(body)}"


class TestNoSilentDefaults:
    """The shared parser must not turn a wire-format change into a neutral-looking number.

    Both the web and browser adapters go through `parse_item`, so a swallow here is worth
    more than a swallow anywhere else in the codebase — and it was the last one left after
    the affiliate adapter was fixed.
    """

    @pytest.mark.parametrize("garbage", ["52%", "half", {}, [], "nan", "inf"])
    def test_an_unreadable_raw_discount_raises_and_names_the_field(self, garbage):
        """Defaulting this to 0 disables the one judgement the app exists to make.

        With `claimed_discount_pct == 0`, `claimed - true_pct` can never exceed the inflation
        tolerance, so `CLAIM_INFLATED` never fires, `is_genuine` stops filtering, the score
        penalty stops applying — and every permanently-"-50%" listing ranks as verified. The
        card then prints "Shopee claims -0%" in calm grey, so the fake listing ends up
        looking *more* trustworthy than an honest one.
        """
        with pytest.raises(ParseError, match="raw_discount"):
            parse_item(item_basic(raw_discount=garbage))

    @pytest.mark.parametrize("absent", [None, "", 0])
    def test_an_absent_raw_discount_is_simply_no_claim(self, absent):
        assert parse_item(item_basic(raw_discount=absent)).claimed_discount_pct == 0

    @pytest.mark.parametrize("garbage", ["4.5 stars", {}, "nan"])
    def test_an_unreadable_rating_star_raises(self, garbage):
        """Becoming None flips rating_is_credible for the whole page at once.

        That silently adds UNRATED_SELLER and its penalty to every listing returned, which
        reranks the entire result set because one field changed shape.
        """
        with pytest.raises(ParseError, match="rating_star"):
            parse_item(item_basic(item_rating={"rating_star": garbage}))

    def test_a_string_rating_count_is_not_indexed_as_a_sequence(self):
        """`str` is a Sequence, so "1234" used to index to "1" and parse as a count of one.

        A count of 1 reads as "barely reviewed" and costs the listing its credibility.
        """
        product = parse_item(
            item_basic(item_rating={"rating_star": 4.5, "rating_count": "1234"})
        )

        assert product.rating_count == 1234

    def test_an_unreadable_sold_count_raises(self):
        with pytest.raises(ParseError, match="historical_sold"):
            parse_item(item_basic(historical_sold="1.2k"))

    def test_one_bad_item_still_costs_only_that_item(self):
        """The page-level policy has to keep holding now that items can raise."""
        good = item_basic(itemid=1)
        bad = item_basic(itemid=2, raw_discount="52%")

        products = parse_search_response({"error": None, "items": [good, bad]})

        assert [p.item_id for p in products] == [1]


class TestFlashSaleFailsLoudly:
    """The flash path had the swallow-and-default shape the search path was fixed for.

    `data.get("items") or []`, a bare `except ParseError: continue`, and no "nothing parsed"
    guard. At 21:00 on 12.12 a renamed field made every entry fail, the chain recorded a
    SUCCESS with zero refusals and zero failures, and the UI said "0 flash deals" during the
    busiest slot of the year.
    """

    def test_an_absent_items_key_raises(self):
        with pytest.raises(ParseError, match="items"):
            parse_flash_sale_response({"error": None, "data": {}})

    def test_an_empty_list_is_a_genuine_quiet_market(self):
        assert parse_flash_sale_response({"error": None, "data": {"items": []}}) == []

    def test_a_page_where_nothing_parses_raises(self):
        broken = [
            item_basic(itemid=1)["item_basic"],
            item_basic(itemid=2)["item_basic"],
        ]
        for entry in broken:
            entry["raw_discount"] = "52%"

        with pytest.raises(ParseError, match="none of 2"):
            parse_flash_sale_response({"error": None, "data": {"items": broken}})

    def test_one_bad_entry_still_costs_only_that_entry(self):
        good = item_basic(itemid=1)["item_basic"]
        bad = item_basic(itemid=2)["item_basic"]
        bad["raw_discount"] = "52%"

        products = parse_flash_sale_response(
            {"error": None, "data": {"items": [good, bad]}}
        )

        assert [p.item_id for p in products] == [1]
        assert products[0].is_flash_sale, "the endpoint guarantees the flag"
