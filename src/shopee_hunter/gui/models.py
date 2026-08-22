"""Qt list models — the only way QML sees domain objects.

QML gets *formatted, presentational* values (``"890.000 ₫"``, ``"−46%"``), not raw model
objects. Two reasons, and they are the same reason: a QML file that reaches into
``deal.product.price.amount`` and does arithmetic on it has business logic in the view layer,
and money formatting duplicated across six delegates drifts. Formatting lives here; the
*judgement* stays in ``core/`` (ADR-005).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar, Optional

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, Qt, Signal, Slot

from ..core.models import Confidence, Deal, DealFlag, Money, PriceSnapshot, Watch

# A shared invalid index for the default argument: constructing one per call in a signature
# default is evaluated once at import anyway, and ruff (B008) is right that it reads as a
# mutable default even though QModelIndex is not.
_NO_PARENT = QModelIndex()

# Vietnamese number formatting: 1.234.567 ₫ (dot as the thousands separator).
_CURRENCY_SUFFIX = {
    "VND": "₫",
    "THB": "฿",
    "SGD": "S$",
    "MYR": "RM",
    "PHP": "₱",
    "IDR": "Rp",
    "BRL": "R$",
}


def format_money(money: Money) -> str:
    """``Money`` → the string a Vietnamese shopper expects to read."""
    grouped = f"{money.amount:,}".replace(",", ".")
    suffix = _CURRENCY_SUFFIX.get(money.currency.value, money.currency.value)
    return f"{grouped} {suffix}"


def format_count(value: int) -> str:
    """Compact sold/rating counts: 12.400 → "12,4k", 1.200.000 → "1,2tr"."""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}".replace(".", ",") + "tr"
    if value >= 1_000:
        return f"{value / 1_000:.1f}".replace(".", ",") + "k"
    return str(value)


_CONFIDENCE_LABEL = {
    Confidence.NONE: "unverified",
    Confidence.LOW: "thin history",
    Confidence.MEDIUM: "verified",
    Confidence.HIGH: "well verified",
}

_FLAG_LABEL = {
    DealFlag.ALL_TIME_LOW: "lowest ever",
    DealFlag.CLAIM_INFLATED: "inflated claim",
    DealFlag.FLASH_SALE: "flash sale",
    DealFlag.PRICE_RISING: "rising",
    DealFlag.THIN_HISTORY: "new listing",
    DealFlag.UNRATED_SELLER: "unrated seller",
    DealFlag.FREE_SHIPPING: "free ship",
}

# Flags the UI must colour as a warning rather than a feature.
_WARNING_FLAGS = frozenset(
    {DealFlag.CLAIM_INFLATED, DealFlag.UNRATED_SELLER, DealFlag.PRICE_RISING}
)


class DealListModel(QAbstractListModel):
    """The ranked deal list behind the Deals view."""

    # Roles start above Qt::UserRole so they cannot collide with Qt's own.
    NameRole = Qt.UserRole + 1
    PriceRole = Qt.UserRole + 2
    ReferenceRole = Qt.UserRole + 3
    SavingsRole = Qt.UserRole + 4
    DiscountRole = Qt.UserRole + 5
    ClaimedDiscountRole = Qt.UserRole + 6
    ScoreRole = Qt.UserRole + 7
    ConfidenceRole = Qt.UserRole + 8
    ConfidenceLabelRole = Qt.UserRole + 9
    FlagsRole = Qt.UserRole + 10
    WarningsRole = Qt.UserRole + 11
    GenuineRole = Qt.UserRole + 12
    ShopRole = Qt.UserRole + 13
    OfficialRole = Qt.UserRole + 14
    RatingRole = Qt.UserRole + 15
    SoldRole = Qt.UserRole + 16
    UrlRole = Qt.UserRole + 17
    ImageRole = Qt.UserRole + 18
    HistoryRole = Qt.UserRole + 19
    WatchRole = Qt.UserRole + 20
    FlashRole = Qt.UserRole + 21

    # The engine's verdict on the seller's claim, as a boolean the view can paint directly.
    # Without it a card has to compare `claimedDiscount` against `discount` itself, which
    # means re-implementing CLAIM_INFLATION_TOLERANCE_PCT in QML where no test can see it.
    ClaimInflatedRole = Qt.UserRole + 22

    countChanged = Signal()

    _ROLE_NAMES: ClassVar[dict[int, bytes]] = {
        NameRole: b"name",
        PriceRole: b"priceText",
        ReferenceRole: b"referenceText",
        SavingsRole: b"savingsText",
        DiscountRole: b"discount",
        ClaimedDiscountRole: b"claimedDiscount",
        ScoreRole: b"score",
        ConfidenceRole: b"confidence",
        ConfidenceLabelRole: b"confidenceLabel",
        FlagsRole: b"flags",
        WarningsRole: b"warnings",
        GenuineRole: b"genuine",
        ShopRole: b"shopName",
        OfficialRole: b"official",
        RatingRole: b"ratingText",
        SoldRole: b"soldText",
        UrlRole: b"url",
        ImageRole: b"imageUrl",
        HistoryRole: b"history",
        WatchRole: b"watchId",
        FlashRole: b"flash",
        ClaimInflatedRole: b"claimInflated",
    }

    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._deals: list[Deal] = []
        self._history: dict[str, list[PriceSnapshot]] = {}

    # -- QAbstractListModel ----------------------------------------------------
    def rowCount(self, parent: QModelIndex = _NO_PARENT) -> int:
        return 0 if parent.isValid() else len(self._deals)

    def roleNames(self) -> dict[int, QByteArray]:
        return {role: QByteArray(name) for role, name in self._ROLE_NAMES.items()}

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._deals):
            return None
        deal = self._deals[index.row()]
        product = deal.product

        if role in (self.NameRole, Qt.DisplayRole):
            return product.name
        if role == self.PriceRole:
            return format_money(product.price)
        if role == self.ReferenceRole:
            return format_money(deal.reference_price)
        if role == self.SavingsRole:
            return format_money(deal.savings)
        if role == self.DiscountRole:
            return round(deal.true_discount_pct, 1)
        if role == self.ClaimedDiscountRole:
            return product.claimed_discount_pct
        if role == self.ScoreRole:
            return deal.score
        if role == self.ConfidenceRole:
            return deal.confidence.value
        if role == self.ConfidenceLabelRole:
            return _CONFIDENCE_LABEL[deal.confidence]
        if role == self.FlagsRole:
            return [
                _FLAG_LABEL[flag]
                for flag in sorted(deal.flags, key=lambda f: f.value)
                if flag not in _WARNING_FLAGS
            ]
        if role == self.WarningsRole:
            return [
                _FLAG_LABEL[flag]
                for flag in sorted(deal.flags, key=lambda f: f.value)
                if flag in _WARNING_FLAGS
            ]
        if role == self.GenuineRole:
            return deal.is_genuine
        if role == self.ShopRole:
            return product.shop.name if product.shop else ""
        if role == self.OfficialRole:
            return bool(product.shop and product.shop.is_official)
        if role == self.RatingRole:
            if not product.rating_is_credible or product.rating is None:
                return ""
            return f"{product.rating:.1f} ({format_count(product.rating_count)})"
        if role == self.SoldRole:
            return (
                f"{format_count(product.sold_count)} sold" if product.sold_count else ""
            )
        if role == self.UrlRole:
            return product.url
        if role == self.ImageRole:
            return product.image_url
        if role == self.HistoryRole:
            return self._sparkline(deal)
        if role == self.WatchRole:
            return deal.watch_id or ""
        if role == self.FlashRole:
            return product.is_flash_sale
        if role == self.ClaimInflatedRole:
            return DealFlag.CLAIM_INFLATED in deal.flags
        return None

    # -- population -------------------------------------------------------------
    def set_deals(
        self,
        deals: Sequence[Deal],
        history: Optional[dict[str, list[PriceSnapshot]]] = None,
    ) -> None:
        """Replace the whole list. A scan produces a new ranking, not a patch of the old one."""
        self.beginResetModel()
        self._deals = list(deals)
        self._history = dict(history or {})
        self.endResetModel()
        self.countChanged.emit()

    def clear(self) -> None:
        self.set_deals([])

    @Slot(int, result="QVariant")
    def get(self, row: int) -> dict[str, Any]:
        """Whole row as an object — for a QML detail pane that wants every field at once."""
        if not 0 <= row < len(self._deals):
            return {}
        index = self.index(row, 0)
        return {
            name.decode(): self.data(index, role)
            for role, name in self._ROLE_NAMES.items()
        }

    def deal_at(self, row: int) -> Optional[Deal]:
        return self._deals[row] if 0 <= row < len(self._deals) else None

    def genuine_count(self) -> int:
        """How many of the rows the engine actually verified.

        Distinct from `rowCount`, which is every deal shown. The header tile is labelled
        "verified deals" and the Settings view promises an inflated claim is "not counted as
        genuine" — both were reading the row count, so a list containing a rejected listing
        reported it as verified anyway.
        """
        return sum(1 for deal in self._deals if deal.is_genuine)

    def _sparkline(self, deal: Deal) -> list[float]:
        """Price history normalised to 0..1 for the card's sparkline.

        Normalised here rather than in QML so the delegate is a pure drawing routine: it
        receives points, not prices, and cannot accidentally invent a scale of its own.
        """
        snapshots = sorted(
            self._history.get(deal.product.key, []), key=lambda s: s.observed_at
        )
        prices = [s.price.amount for s in snapshots] + [deal.product.price.amount]
        if len(prices) < 2:
            return []
        low, high = min(prices), max(prices)
        if high == low:
            return [0.5] * len(prices)
        return [(price - low) / (high - low) for price in prices]


class WatchListModel(QAbstractListModel):
    """The user's watches, for the Watches view."""

    IdRole = Qt.UserRole + 1
    KeywordRole = Qt.UserRole + 2
    MaxPriceRole = Qt.UserRole + 3
    MinDiscountRole = Qt.UserRole + 4
    MinRatingRole = Qt.UserRole + 5
    ExcludeRole = Qt.UserRole + 6
    EnabledRole = Qt.UserRole + 7
    OfficialRole = Qt.UserRole + 8

    countChanged = Signal()

    _ROLE_NAMES: ClassVar[dict[int, bytes]] = {
        IdRole: b"watchId",
        KeywordRole: b"keyword",
        MaxPriceRole: b"maxPriceText",
        MinDiscountRole: b"minDiscount",
        MinRatingRole: b"minRating",
        ExcludeRole: b"excludeText",
        EnabledRole: b"enabled",
        OfficialRole: b"officialOnly",
    }

    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._watches: list[Watch] = []

    def rowCount(self, parent: QModelIndex = _NO_PARENT) -> int:
        return 0 if parent.isValid() else len(self._watches)

    def roleNames(self) -> dict[int, QByteArray]:
        return {role: QByteArray(name) for role, name in self._ROLE_NAMES.items()}

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._watches):
            return None
        watch = self._watches[index.row()]
        if role in (self.KeywordRole, Qt.DisplayRole):
            return watch.keyword
        if role == self.IdRole:
            return watch.watch_id
        if role == self.MaxPriceRole:
            return format_money(watch.max_price) if watch.max_price else "any price"
        if role == self.MinDiscountRole:
            return watch.min_discount_pct
        if role == self.MinRatingRole:
            return watch.min_rating if watch.min_rating is not None else 0.0
        if role == self.ExcludeRole:
            return ", ".join(watch.exclude_terms)
        if role == self.EnabledRole:
            return watch.enabled
        if role == self.OfficialRole:
            return watch.official_only
        return None

    def set_watches(self, watches: Sequence[Watch]) -> None:
        self.beginResetModel()
        self._watches = list(watches)
        self.endResetModel()
        self.countChanged.emit()

    def watch_at(self, row: int) -> Optional[Watch]:
        return self._watches[row] if 0 <= row < len(self._watches) else None
