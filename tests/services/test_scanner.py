"""Scan orchestration: the ORDER of operations, and what happens when a source misbehaves."""

from __future__ import annotations

import pytest

from shopee_hunter.core.errors import SourceAuthRequired, SourceBlocked, SourceError
from shopee_hunter.core.models import Money, SearchQuery, Watch
from shopee_hunter.services.scanner import Scanner


class FakeChain:
    """Stands in for a SourceChain: answers from a script, records the queries it saw."""

    def __init__(self, behaviour=None):
        self.behaviour = list(behaviour or [])
        self.queries: list[SearchQuery] = []
        self.last_source = "fake"

    async def search(self, query: SearchQuery):
        self.queries.append(query)
        step = self.behaviour.pop(0) if self.behaviour else []
        if isinstance(step, Exception):
            raise step
        return list(step)

    async def flash_sale(self, limit: int = 60):
        step = self.behaviour.pop(0) if self.behaviour else []
        if isinstance(step, Exception):
            raise step
        return list(step)

    async def aclose(self) -> None:
        return None


@pytest.fixture
def scanner(settings, repository):
    return Scanner(settings, FakeChain(), repository)


class TestScanKeyword:
    async def test_records_a_snapshot_for_every_listing_even_with_no_deals(
        self, settings, repository, product_factory
    ):
        """A scan that finds nothing still builds the history the next one reasons over."""
        chain = FakeChain([[product_factory(item_id=1), product_factory(item_id=2)]])
        result = await Scanner(settings, chain, repository).scan_keyword("tai nghe")

        assert result.products_seen == 2
        assert result.snapshots_written == 2
        await repository.close()

    async def test_the_current_observation_is_not_part_of_its_own_baseline(
        self, settings, repository, product_factory
    ):
        """Otherwise every first sighting evaluates as a 0% discount."""
        product = product_factory(item_id=1, price=100_000, before=300_000)
        chain = FakeChain([[product]])
        settings.scan.min_discount_pct = 5.0

        result = await Scanner(settings, chain, repository).scan_keyword("tai nghe")

        assert (
            result.deals
        ), "the scan's own snapshot must not flatten its discount to zero"
        await repository.close()

    async def test_duplicates_across_pages_are_collapsed(
        self, settings, repository, product_factory
    ):
        chain = FakeChain(
            [
                [
                    product_factory(item_id=1, price=300_000),
                    product_factory(item_id=1, price=100_000),
                ]
            ]
        )

        result = await Scanner(settings, chain, repository).scan_keyword("tai nghe")

        assert result.products_seen == 1
        await repository.close()

    async def test_a_refusal_is_reported_as_a_refusal(self, settings, repository):
        chain = FakeChain([SourceBlocked("refused", source="fake")])

        result = await Scanner(settings, chain, repository).scan_keyword("tai nghe")

        assert result.blocked
        assert not result.broken
        assert result.refusals
        await repository.close()

    async def test_a_parse_failure_is_not_a_refusal(self, settings, repository):
        """These need different responses: one is "wait", the other is "fix the parser"."""
        from shopee_hunter.core.errors import ParseError

        chain = FakeChain([ParseError("field moved", source="fake")])

        result = await Scanner(settings, chain, repository).scan_keyword("tai nghe")

        assert result.broken
        assert not result.blocked
        await repository.close()

    async def test_the_answering_source_is_recorded(
        self, settings, repository, product_factory
    ):
        """A fallback chain must never hide which adapter actually answered."""
        chain = FakeChain([[product_factory()]])

        result = await Scanner(settings, chain, repository).scan_keyword("tai nghe")

        assert result.source_used == "fake"
        await repository.close()

    async def test_the_max_price_filter_reaches_the_query(self, settings, repository):
        chain = FakeChain([[]])

        await Scanner(settings, chain, repository).scan_keyword(
            "tai nghe", max_price=500_000
        )

        assert chain.queries[0].max_price == Money(500_000)
        await repository.close()


class TestScanWatches:
    async def test_scans_every_enabled_watch(
        self, settings, repository, product_factory
    ):
        chain = FakeChain([[product_factory(item_id=1)], [product_factory(item_id=2)]])
        watches = [
            Watch("a", "tai nghe", min_rating=None, min_discount_pct=0.0),
            Watch("b", "ban phim", min_rating=None, min_discount_pct=0.0),
        ]

        await Scanner(settings, chain, repository).scan_watches(watches)

        assert [query.keyword for query in chain.queries] == ["tai nghe", "ban phim"]
        await repository.close()

    async def test_disabled_watches_are_skipped(self, settings, repository):
        chain = FakeChain([[]])

        await Scanner(settings, chain, repository).scan_watches(
            [Watch("a", "tai nghe", enabled=False)]
        )

        assert chain.queries == []
        await repository.close()

    async def test_a_refusal_abandons_the_rest_of_the_scan(self, settings, repository):
        """Every remaining watch would hit the same wall and deepen the penalty."""
        chain = FakeChain([SourceBlocked("refused", source="fake"), []])
        watches = [Watch("a", "tai nghe"), Watch("b", "ban phim")]

        result = await Scanner(settings, chain, repository).scan_watches(watches)

        assert len(chain.queries) == 1
        assert result.blocked
        await repository.close()

    async def test_an_auth_refusal_also_stops_the_scan(self, settings, repository):
        chain = FakeChain([SourceAuthRequired("log in", source="fake")])

        result = await Scanner(settings, chain, repository).scan_watches(
            [Watch("a", "tai nghe")]
        )

        assert result.blocked
        await repository.close()

    async def test_a_single_watch_failing_does_not_stop_the_others(
        self, settings, repository, product_factory
    ):
        chain = FakeChain(
            [SourceError("odd", source="fake"), [product_factory(item_id=2)]]
        )
        watches = [
            Watch("a", "tai nghe", min_rating=None),
            Watch("b", "ban phim", min_rating=None),
        ]

        result = await Scanner(settings, chain, repository).scan_watches(watches)

        assert len(chain.queries) == 2
        assert result.failures
        assert result.products_seen == 1
        await repository.close()

    async def test_progress_is_reported_per_watch(self, settings, repository):
        chain = FakeChain([[], []])
        seen: list[tuple[int, int, str]] = []

        await Scanner(settings, chain, repository).scan_watches(
            [Watch("a", "tai nghe"), Watch("b", "ban phim")],
            progress=lambda done, total, label: seen.append((done, total, label)),
        )

        assert seen[0] == (0, 2, "tai nghe")
        assert seen[-1] == (2, 2, "evaluating")
        await repository.close()

    async def test_deals_are_tagged_with_the_watch_that_matched(
        self, settings, repository, product_factory
    ):
        chain = FakeChain(
            [
                [
                    product_factory(
                        item_id=1, name="Tai nghe X", price=100_000, before=300_000
                    )
                ]
            ]
        )
        watches = [Watch("audio", "tai nghe", min_rating=None, min_discount_pct=5.0)]

        result = await Scanner(settings, chain, repository).scan_watches(watches)

        assert result.deals
        assert result.deals[0].watch_id == "audio"
        await repository.close()

    async def test_no_watches_is_an_empty_result_not_an_error(
        self, settings, repository
    ):
        result = await Scanner(settings, FakeChain(), repository).scan_watches([])

        assert result.deals == []
        assert result.finished_at is not None
        await repository.close()


class TestNotifiable:
    async def test_only_high_scoring_genuine_deals_qualify(
        self, settings, repository, product_factory, snapshot_factory
    ):
        settings.scan.notify_min_score = 60.0
        settings.scan.notify_on_new_deal = True
        product = product_factory(item_id=1, price=100_000, before=300_000)
        await repository.record_snapshots(
            snapshot_products(product, snapshot_factory(300_000, count=14))
        )

        chain = FakeChain([[product]])
        scanner = Scanner(settings, chain, repository)
        result = await scanner.scan_keyword("tai nghe")

        notifiable = await scanner.notifiable(result)

        assert all(deal.score >= 60.0 and deal.is_genuine for deal in notifiable)
        await repository.close()

    async def test_nothing_is_notifiable_when_notifications_are_off(
        self, settings, repository, product_factory
    ):
        settings.scan.notify_on_new_deal = False
        chain = FakeChain([[product_factory(price=100_000, before=300_000)]])
        scanner = Scanner(settings, chain, repository)

        assert await scanner.notifiable(await scanner.scan_keyword("tai nghe")) == []
        await repository.close()

    async def test_the_same_deal_is_not_announced_twice(
        self, settings, repository, product_factory, snapshot_factory
    ):
        settings.scan.notify_min_score = 0.0
        product = product_factory(item_id=1, price=100_000, before=300_000)
        await repository.record_snapshots(
            snapshot_products(product, snapshot_factory(300_000, count=14))
        )
        scanner = Scanner(settings, FakeChain([[product], [product]]), repository)

        first = await scanner.notifiable(await scanner.scan_keyword("tai nghe"))
        second = await scanner.notifiable(await scanner.scan_keyword("tai nghe"))

        assert first
        assert (
            second == []
        ), "re-announcing an unchanged deal is how a user learns to mute us"
        await repository.close()


def snapshot_products(product, snapshots):
    """Turn snapshots back into products so they can go through record_snapshots."""
    from dataclasses import replace

    return [
        replace(product, price=snapshot.price, captured_at=snapshot.observed_at)
        for snapshot in snapshots
    ]
