"""Demo mode: a full, believable app with no network and no credentials.

It exists because of an honest property of this app — on a fresh install there is no price
history, so every verdict is ``Confidence.NONE`` and the deal list is a wall of "unverified"
(ADR-005). That is the correct behaviour and a terrible first impression, and it makes the UI
impossible to screenshot or review.

So demo mode seeds the same things a month of real use would: a handful of watches, and a
price history behind each demo listing. Everything is deterministic (a fixed seed), which is
what makes ``scripts/ui_screenshot.py`` output diffable between commits.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..core.logging import get_logger
from ..core.models import Money, Watch
from ..sources.base import SourceChain
from ..sources.fixture import FixtureSource
from ..storage.repository import Repository

log = get_logger("services.demo")

# Chosen to span the shapes the UI must render: a genuine bargain, an inflated claim, a
# thin-history listing, an unrated seller, and a flash-sale item.
DEMO_WATCHES: tuple[Watch, ...] = (
    Watch(
        "demo-audio",
        "tai nghe",
        max_price=Money(2_000_000),
        min_discount_pct=15.0,
        min_rating=4.0,
    ),
    Watch(
        "demo-keyboard",
        "ban phim",
        max_price=Money(3_000_000),
        min_discount_pct=10.0,
        min_rating=4.0,
    ),
    Watch(
        "demo-mouse",
        "chuot",
        max_price=Money(1_000_000),
        min_discount_pct=15.0,
        min_rating=4.0,
    ),
    Watch(
        "demo-monitor",
        "man hinh",
        max_price=Money(5_000_000),
        min_discount_pct=10.0,
        min_rating=4.5,
    ),
    Watch(
        "demo-ssd",
        "ssd",
        max_price=Money(3_000_000),
        min_discount_pct=10.0,
        min_rating=4.5,
    ),
    Watch(
        "demo-phone-acc",
        "op lung",
        max_price=Money(200_000),
        min_discount_pct=30.0,
        min_rating=None,
        exclude_terms=("cuong luc",),
    ),
    Watch(
        "demo-home",
        "noi chien",
        max_price=Money(2_500_000),
        min_discount_pct=20.0,
        min_rating=4.5,
    ),
    Watch(
        "demo-skincare",
        "kem chong nang",
        max_price=Money(600_000),
        min_discount_pct=15.0,
        min_rating=4.5,
    ),
    Watch(
        "demo-bag",
        "balo",
        max_price=Money(500_000),
        min_discount_pct=25.0,
        min_rating=None,
    ),
    Watch(
        "demo-fashion",
        "ao thun",
        max_price=Money(300_000),
        min_discount_pct=30.0,
        min_rating=None,
    ),
)


async def seed_demo(repository: Repository, chain: SourceChain) -> int:
    """Populate watches and price history for the demo catalogue.

    Idempotent: snapshots are unique per (listing, timestamp) and watches upsert by id, so
    running this at every launch neither duplicates nor drifts.

    Returns:
        How many history snapshots were written this call.
    """
    fixture = next((a for a in chain.adapters if isinstance(a, FixtureSource)), None)
    if fixture is None:
        log.debug("no fixture adapter in the chain; skipping demo seed")
        return 0

    for watch in DEMO_WATCHES:
        await repository.save_watch(watch)

    written = 0
    for product in fixture._demo_catalogue():
        history = fixture.demo_history(product)
        written += await repository.record_snapshots(
            [_product_at(product, snapshot) for snapshot in history]
        )
    log.info("demo mode: %d watches, %d history snapshots", len(DEMO_WATCHES), written)
    return written


def _product_at(product, snapshot):  # type: ignore[no-untyped-def]
    """Re-date a demo product onto one of its historical snapshots.

    Snapshots are written through ``record_snapshots`` (rather than a second insert path) so
    demo data goes through exactly the code real scans do — a demo that bypasses the
    repository proves nothing about the repository.
    """
    from dataclasses import replace

    return replace(product, price=snapshot.price, captured_at=snapshot.observed_at)


def demo_watch_ids() -> Sequence[str]:
    return tuple(watch.watch_id for watch in DEMO_WATCHES)
