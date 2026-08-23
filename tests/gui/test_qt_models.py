"""The Qt list models: formatting, roles, and the sparkline normalisation.

These are the boundary where domain objects become presentation. The formatting lives here
precisely so it is testable — a delegate doing its own number formatting is not.
"""

from __future__ import annotations

import pytest

from shopee_hunter.core.models import Currency, Money, Watch
from shopee_hunter.gui.models import (
    DealListModel,
    WatchListModel,
    format_count,
    format_money,
)


class TestFormatting:
    @pytest.mark.parametrize(
        ("amount", "expected"),
        [
            (0, "0 ₫"),
            (1_000, "1.000 ₫"),
            (129_000, "129.000 ₫"),
            (2_349_834, "2.349.834 ₫"),
        ],
    )
    def test_money_uses_vietnamese_grouping(self, amount, expected):
        assert format_money(Money(amount)) == expected

    def test_other_currencies_get_their_own_symbol(self):
        assert format_money(Money(50, Currency.SGD)) == "50 S$"

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0, "0"),
            (999, "999"),
            (1_200, "1,2k"),
            (12_400, "12,4k"),
            (1_200_000, "1,2tr"),
        ],
    )
    def test_counts_are_compact(self, value, expected):
        assert format_count(value) == expected


class TestDealListModel:
    @pytest.fixture
    def model(self, product_factory, snapshot_factory, now):
        from shopee_hunter.core.deals import evaluate

        deal = evaluate(
            product_factory(price=200_000, before=400_000, claimed=50),
            snapshot_factory(390_000, count=14),
            now=now,
        )
        model = DealListModel()
        model.set_deals([deal], {deal.product.key: snapshot_factory(390_000, count=14)})
        return model

    def test_exposes_one_row(self, model):
        assert model.rowCount() == 1

    def test_role_names_are_what_qml_binds_to(self, model):
        names = {bytes(name).decode() for name in model.roleNames().values()}

        # Every one of these is referenced by DealCard.qml; a rename breaks the view silently.
        assert {
            "name",
            "priceText",
            "referenceText",
            "discount",
            "score",
            "confidence",
            "confidenceLabel",
            "flags",
            "warnings",
            "history",
            "url",
            "claimInflated",
        } <= names

    def test_prices_arrive_formatted_not_raw(self, model):
        row = model.get(0)

        assert row["priceText"] == "200.000 ₫"
        assert row["referenceText"].endswith("₫")

    def test_warnings_are_separated_from_positive_flags(
        self, product_factory, snapshot_factory, now
    ):
        from shopee_hunter.core.deals import evaluate

        # A claim of 50% against a flat price: inflated.
        deal = evaluate(
            product_factory(price=200_000, before=400_000, claimed=50),
            snapshot_factory(205_000, count=14),
            now=now,
        )
        model = DealListModel()
        model.set_deals([deal])

        row = model.get(0)

        assert "inflated claim" in row["warnings"]
        assert (
            "inflated claim" not in row["flags"]
        ), "a fake discount must never be rendered among the positive badges"

    def test_claim_inflated_is_exposed_as_the_engines_verdict(
        self, product_factory, snapshot_factory, now
    ):
        """The card paints a suspicious claim; the engine decides what is suspicious.

        DealCard.qml used to colour the "Shopee claims −N%" line with its own
        `claimedDiscount - discount > 15`, a copy of CLAIM_INFLATION_TOLERANCE_PCT. Retuning
        the constant in core/deals.py would then drop a listing from `is_genuine` while the
        card still painted its claim in calm grey — the UI quietly failing to warn about
        exactly the listings this app exists to catch, with no test going red.
        """
        from shopee_hunter.core.deals import evaluate

        # Claimed 50% against a price that has barely moved: the engine calls it inflated.
        inflated = evaluate(
            product_factory(price=200_000, before=400_000, claimed=50),
            snapshot_factory(205_000, count=14),
            now=now,
        )
        # The same claim, this time matched by a real drop from the observed baseline.
        honest = evaluate(
            product_factory(price=200_000, before=400_000, claimed=50),
            snapshot_factory(390_000, count=14),
            now=now,
        )
        model = DealListModel()

        model.set_deals([inflated])
        assert model.get(0)["claimInflated"] is True
        assert "inflated claim" in model.get(0)["warnings"]

        model.set_deals([honest])
        assert model.get(0)["claimInflated"] is False
        assert "inflated claim" not in model.get(0)["warnings"]

    def test_an_uncredible_rating_is_not_displayed(self, product_factory):
        from shopee_hunter.core.deals import evaluate

        model = DealListModel()
        model.set_deals([evaluate(product_factory(rating=5.0, rating_count=2))])

        assert model.get(0)["ratingText"] == ""

    def test_sparkline_is_normalised_to_zero_one(self, model):
        points = model.get(0)["history"]

        assert points
        assert min(points) == pytest.approx(0.0)
        assert max(points) == pytest.approx(1.0)

    def test_sparkline_is_empty_without_history(self, product_factory):
        from shopee_hunter.core.deals import evaluate

        model = DealListModel()
        model.set_deals([evaluate(product_factory())])

        assert model.get(0)["history"] == []

    def test_a_flat_history_does_not_divide_by_zero(
        self, product_factory, snapshot_factory, now
    ):
        from shopee_hunter.core.deals import evaluate

        product = product_factory(price=200_000, before=None)
        history = snapshot_factory(200_000, count=5)
        deal = evaluate(product, history, now=now)
        model = DealListModel()
        model.set_deals([deal], {product.key: history})

        assert set(model.get(0)["history"]) == {0.5}

    def test_out_of_range_rows_are_empty_rather_than_an_error(self, model):
        assert model.get(99) == {}
        assert model.deal_at(99) is None

    def test_clear_empties_the_model(self, model):
        model.clear()

        assert model.rowCount() == 0


class TestWatchListModel:
    def test_formats_the_ceiling_and_says_when_there_is_none(self):
        model = WatchListModel()
        model.set_watches(
            [
                Watch("a", "tai nghe", max_price=Money(500_000)),
                Watch("b", "ban phim", max_price=None),
            ]
        )

        assert model.data(model.index(0, 0), WatchListModel.MaxPriceRole) == "500.000 ₫"
        assert model.data(model.index(1, 0), WatchListModel.MaxPriceRole) == "any price"

    def test_exclusions_are_joined_for_display(self):
        model = WatchListModel()
        model.set_watches(
            [Watch("a", "op lung", exclude_terms=("cuong luc", "dan man"))]
        )

        assert (
            model.data(model.index(0, 0), WatchListModel.ExcludeRole)
            == "cuong luc, dan man"
        )

    def test_no_rating_floor_reads_as_zero_for_qml(self):
        """QML has no null for a number; 0 is the documented sentinel."""
        model = WatchListModel()
        model.set_watches([Watch("a", "tai nghe", min_rating=None)])

        assert model.data(model.index(0, 0), WatchListModel.MinRatingRole) == 0.0


class TestTierTone:
    """The tier → badge-tone mapping the views used to make for themselves.

    `CalendarView.qml` and `AppWindow.qml` both asked `bridge.tierLevel >= 3`, which encodes
    which `SaleTier` members are campaigns. Insert a tier below MEGA and every one of those
    comparisons shifts by one, so 12.12 renders as a neutral grey badge on the single day the
    app exists to shout about — silently, with the suite green.
    """

    @pytest.mark.parametrize(
        ("tier", "tone"),
        [
            ("QUIET", "neutral"),
            ("FLASH_SLOT", "caution"),
            ("PAYDAY", "caution"),
            ("DOUBLE_DATE", "accent"),
            ("MEGA", "accent"),
        ],
    )
    def test_each_tier_gets_its_tone(self, tier: str, tone: str) -> None:
        from shopee_hunter.core.sale_calendar import SaleTier
        from shopee_hunter.gui.bridge import tone_for_tier

        assert tone_for_tier(SaleTier[tier]) == tone

    def test_every_tone_is_one_the_badge_component_understands(self) -> None:
        """A tone string the Badge does not know renders as its neutral fallback, silently."""
        from pathlib import Path

        from shopee_hunter.core.sale_calendar import SaleTier
        from shopee_hunter.gui.bridge import tone_for_tier

        badge = (
            Path(__file__).resolve().parents[2]
            / "src/shopee_hunter/gui/qml/components/Badge.qml"
        ).read_text(encoding="utf-8")

        for tier in SaleTier:
            assert f'"{tone_for_tier(tier)}"' in badge, (
                f"{tier.name} maps to tone {tone_for_tier(tier)!r}, which Badge.qml does "
                f"not handle"
            )
