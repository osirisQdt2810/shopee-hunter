"""The offline adapter: recorded responses, or a deterministic demo catalogue.

It exists for three jobs, all of which need data without touching the network:

* the offline test tier (ADR-008) replays *captured* responses, so parsing tracks reality;
* ``--demo`` and the UI screenshot script get a full, pretty window with no requests;
* a new contributor can run the app before deciding whether to set up credentials.

The synthesised catalogue is deliberately varied — a genuine all-time low, an inflated
"-70%" claim, a thin-history listing, an unrated seller — so the UI's badges and the deal
engine's verdicts are all exercised by just launching the app.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, Optional

from ..core.errors import ParseError, SourceUnavailable
from ..core.models import Money, PriceSnapshot, Product, SearchQuery, Shop
from ..core.rate_limit import AsyncTokenBucket
from ..core.settings import AppSettings
from .base import SourceAdapter
from .parse import parse_search_response
from .registry import register_source

# Fixtures live next to the tests that pin them; the adapter finds them from the repo root so
# the same file serves `pytest` and a manual `--source fixture` run.
DEFAULT_FIXTURE_DIR = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "shopee_web"
)

# A fixed seed keeps the demo catalogue byte-identical between runs, which is what makes a UI
# screenshot diffable and a demo-mode test assertable.
DEMO_SEED = 20261212

_DEMO_SPECS: tuple[tuple[str, int, int, int, float, int, bool, bool], ...] = (
    # name, price, claimed_before, claimed_pct, rating, sold, official, flash
    (
        "Tai nghe Bluetooth Soundcore Q30 chống ồn",
        890_000,
        1_790_000,
        50,
        4.8,
        12_400,
        True,
        True,
    ),
    (
        "Bàn phím cơ Akko 3068B Plus hotswap",
        1_290_000,
        1_490_000,
        13,
        4.9,
        3_180,
        True,
        False,
    ),
    ("Chuột Logitech G304 Lightspeed", 449_000, 899_000, 50, 4.7, 28_900, True, False),
    ("Áo thun cotton unisex form rộng", 79_000, 299_000, 74, 4.4, 51_200, False, True),
    (
        "Nồi chiên không dầu Lock&Lock 5.2L",
        1_190_000,
        2_490_000,
        52,
        4.8,
        2_040,
        True,
        False,
    ),
    (
        "Sữa rửa mặt CeraVe 473ml chính hãng",
        319_000,
        450_000,
        29,
        4.9,
        18_700,
        True,
        False,
    ),
    (
        "Ốp lưng iPhone 15 Pro Max trong suốt",
        29_000,
        149_000,
        81,
        4.2,
        96_300,
        False,
        False,
    ),
    (
        "Màn hình Dell S2421HN 24 inch IPS 75Hz",
        2_690_000,
        3_290_000,
        18,
        4.9,
        640,
        True,
        False,
    ),
    (
        "Balo laptop chống nước 15.6 inch",
        189_000,
        590_000,
        68,
        4.5,
        22_100,
        False,
        True,
    ),
    ("Kem chống nắng Anessa Gold 60ml", 389_000, 520_000, 25, 4.9, 9_800, True, False),
    ("Quạt tích điện mini cầm tay", 99_000, 399_000, 75, 3.9, 1_240, False, False),
    ("SSD Samsung 980 NVMe 1TB", 1_690_000, 2_190_000, 23, 5.0, 1_870, True, False),
)


@register_source("fixture")
class FixtureSource(SourceAdapter):
    """Serves recorded JSON when it exists, otherwise a synthetic demo catalogue."""

    label = "Offline fixture / demo"
    supports_flash_sale = True

    def __init__(
        self,
        settings: AppSettings,
        *,
        limiter: Any = None,
        fixture_dir: Optional[Path] = None,
    ) -> None:
        # The shared limiter is ignored on purpose: it exists to protect Shopee from us, and
        # this adapter never contacts Shopee. Throttling a local file read would make demo
        # mode and the offline test suite artificially slow (a 10-watch demo scan took 12
        # seconds at 0.5 req/s) for no benefit to anyone.
        super().__init__(settings, limiter=AsyncTokenBucket(rate=1000.0, burst=1000))
        self.fixture_dir = fixture_dir or DEFAULT_FIXTURE_DIR

    # -- adapter contract -------------------------------------------------------
    async def _do_search(self, query: SearchQuery) -> list[Product]:
        recorded = self._load("search_items.json")
        if recorded is not None:
            products = parse_search_response(
                recorded, currency=self.currency, source=self.id
            )
        else:
            products = self._demo_catalogue()

        keyword = query.keyword.strip().lower()
        if keyword:
            # Match on the whole keyword and on each token, so "tai nghe" and "bluetooth"
            # both hit the earbuds — the demo has to feel like a search, not a fixed list.
            tokens = [t for t in keyword.split() if len(t) > 2]
            products = [
                p
                for p in products
                if keyword in p.name.lower() or any(t in p.name.lower() for t in tokens)
            ] or products
        if query.max_price is not None:
            products = [p for p in products if p.price.amount <= query.max_price.amount]
        if query.min_rating is not None:
            products = [p for p in products if (p.rating or 0.0) >= query.min_rating]
        return products[: query.limit]

    async def _do_fetch_item(self, item_id: int, shop_id: int) -> Product:
        for product in self._demo_catalogue():
            if product.item_id == item_id and product.shop_id == shop_id:
                return product
        raise SourceUnavailable(
            f"no fixture for item {shop_id}_{item_id}", source=self.id
        )

    async def _do_flash_sale(self, limit: int) -> list[Product]:
        return [p for p in self._demo_catalogue() if p.is_flash_sale][:limit]

    # -- fixture loading --------------------------------------------------------
    def _load(self, name: str) -> Optional[dict[str, Any]]:
        path = self.fixture_dir / name
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ParseError(
                f"fixture {path} is unreadable: {exc}", source=self.id
            ) from exc
        if not isinstance(payload, dict):
            raise ParseError(f"fixture {path} is not a JSON object", source=self.id)
        return payload

    # -- synthetic demo data ----------------------------------------------------
    def _demo_catalogue(self) -> list[Product]:
        now = datetime.now(UTC)
        rng = random.Random(DEMO_SEED)
        products: list[Product] = []
        for index, spec in enumerate(_DEMO_SPECS):
            name, price, before, claimed, rating, sold, official, flash = spec
            products.append(
                Product(
                    item_id=100_000 + index,
                    shop_id=9_000 + (index % 4),
                    name=name,
                    price=Money(price, self.currency),
                    price_before_discount=Money(before, self.currency),
                    claimed_discount_pct=claimed,
                    rating=rating,
                    # An unrated seller needs to exist for the badge to be exercised.
                    rating_count=0 if index == 10 else max(12, sold // 8),
                    sold_count=sold,
                    stock=rng.randint(3, 400),
                    image_url="",
                    shop=Shop(
                        shop_id=9_000 + (index % 4),
                        name=("Official Store" if official else "Shop bán lẻ")
                        + f" #{index % 4 + 1}",
                        location="TP. Hồ Chí Minh" if index % 2 else "Hà Nội",
                        is_official=official,
                        is_preferred=not official and index % 3 == 0,
                    ),
                    is_flash_sale=flash,
                    has_free_shipping=index % 3 != 2,
                    vouchers=("Giảm 30k",) if index % 4 == 0 else (),
                    captured_at=now,
                )
            )
        return products

    # Which shape of history each demo listing gets. This is the demo's real content: the
    # app's whole thesis is that a claimed discount and an observed one are different
    # numbers, so the catalogue has to contain both kinds and the UI has to be legible with
    # both on screen at once.
    #   "honest"   — history sits near the claimed original, so the claim verifies
    #   "inflated" — history is flat at today's price: the "-74%" never existed
    #   "thin"     — two days of history: a real drop we cannot yet vouch for
    _HISTORY_SHAPE: ClassVar[dict[int, str]] = {
        0: "honest",
        1: "honest",
        2: "honest",
        3: "inflated",
        4: "honest",
        5: "honest",
        6: "thin",
        7: "honest",
        8: "inflated",
        9: "honest",
        10: "thin",
        11: "honest",
    }

    def demo_history(self, product: Product) -> list[PriceSnapshot]:
        """Plausible price history for a demo product.

        Shaped so the deal engine produces every verdict the UI can render — a verified
        all-time low, an inflated claim, and a drop with too little history to trust.
        """
        now = product.captured_at
        rng = random.Random(DEMO_SEED + product.item_id)
        index = product.item_id - 100_000
        shape = self._HISTORY_SHAPE.get(index, "honest")
        claimed_before = (
            product.price_before_discount.amount
            if product.price_before_discount
            else int(product.price.amount * 1.4)
        )

        if shape == "thin":
            days, base = 3, int(claimed_before * 0.9)
        elif shape == "inflated":
            days, base = 45, product.price.amount  # flat: the claim is fiction
        else:
            # Just under the claimed original, so the claim roughly verifies and the drop is
            # real — with enough span to earn Confidence.HIGH.
            days, base = 60, int(claimed_before * rng.uniform(0.88, 0.99))

        return [
            PriceSnapshot(
                item_id=product.item_id,
                shop_id=product.shop_id,
                price=Money(
                    int(base * rng.uniform(0.97, 1.06)), product.price.currency
                ),
                observed_at=now - timedelta(days=day),
            )
            for day in range(1, days, 3)
        ]
