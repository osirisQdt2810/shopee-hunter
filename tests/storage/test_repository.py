"""Price history is load-bearing (ADR-005), so these tests are about not losing or
double-counting an observation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from shopee_hunter.core.models import Money, Watch


class TestSnapshots:
    async def test_records_one_snapshot_per_product(self, repository, product_factory):
        written = await repository.record_snapshots(
            [product_factory(item_id=1), product_factory(item_id=2)]
        )

        assert written == 2
        await repository.close()

    async def test_recording_the_same_observation_twice_is_idempotent(
        self, repository, product_factory
    ):
        """A retried scan must not fabricate a second data point and shift the median."""
        products = [product_factory(item_id=1)]

        assert await repository.record_snapshots(products) == 1
        assert await repository.record_snapshots(products) == 0
        assert len(await repository.history_for(1, 100)) == 1
        await repository.close()

    async def test_history_comes_back_newest_first(
        self, repository, product_factory, now
    ):
        for days, price in ((3, 300_000), (1, 100_000), (2, 200_000)):
            await repository.record_snapshots(
                [
                    _at(
                        product_factory(item_id=1, price=price),
                        now - timedelta(days=days),
                    )
                ]
            )

        history = await repository.history_for(1, 100)

        assert [snapshot.price.amount for snapshot in history] == [
            100_000,
            200_000,
            300_000,
        ]
        await repository.close()

    async def test_lookback_excludes_ancient_history(self, repository, product_factory):
        old = _at(product_factory(item_id=1), datetime.now(UTC) - timedelta(days=400))
        await repository.record_snapshots([old])

        assert await repository.history_for(1, 100, lookback_days=90) == []
        assert len(await repository.history_for(1, 100, lookback_days=500)) == 1
        await repository.close()

    async def test_many_listings_in_one_query(self, repository, product_factory):
        await repository.record_snapshots(
            [
                product_factory(item_id=1, shop_id=100),
                product_factory(item_id=2, shop_id=200),
            ]
        )

        grouped = await repository.history_for_many([(1, 100), (2, 200)])

        assert set(grouped) == {"100_1", "200_2"}
        await repository.close()

    async def test_asking_for_nothing_returns_nothing(self, repository):
        assert await repository.history_for_many([]) == {}
        await repository.close()

    async def test_flash_prices_are_stored_as_flash(self, repository, product_factory):
        await repository.record_snapshots([product_factory(item_id=1, flash=True)])

        assert (await repository.history_for(1, 100))[0].is_flash_sale
        await repository.close()

    async def test_currency_survives_a_round_trip(self, repository, product_factory):
        from shopee_hunter.core.models import Currency

        product = _with_price(product_factory(item_id=1), Money(1_000, Currency.SGD))
        await repository.record_snapshots([product])

        assert (await repository.history_for(1, 100))[0].price.currency is Currency.SGD
        await repository.close()

    async def test_prune_removes_only_old_rows(self, repository, product_factory):
        await repository.record_snapshots(
            [
                _at(
                    product_factory(item_id=1),
                    datetime.now(UTC) - timedelta(days=500),
                ),
                _at(
                    product_factory(item_id=2),
                    datetime.now(UTC) - timedelta(days=1),
                ),
            ]
        )

        removed = await repository.prune_history(keep_days=365)

        assert removed == 1
        assert (await repository.stats())["snapshots"] == 1
        await repository.close()

    async def test_product_metadata_is_refreshed_not_duplicated(
        self, repository, product_factory
    ):
        await repository.record_snapshots([product_factory(item_id=1, name="Old name")])
        await repository.record_snapshots(
            [
                _at(
                    product_factory(item_id=1, name="New name"),
                    datetime.now(UTC),
                )
            ]
        )

        assert (await repository.stats())["products"] == 1
        await repository.close()


class TestWatches:
    async def test_round_trip(self, repository):
        watch = Watch(
            "w1",
            "tai nghe",
            max_price=Money(500_000),
            exclude_terms=("op lung", "cuong luc"),
        )

        await repository.save_watch(watch)
        [stored] = await repository.list_watches()

        assert stored.watch_id == "w1"
        assert stored.max_price == Money(500_000)
        assert stored.exclude_terms == ("op lung", "cuong luc")
        await repository.close()

    async def test_saving_the_same_id_updates_rather_than_duplicates(self, repository):
        await repository.save_watch(Watch("w1", "tai nghe"))
        await repository.save_watch(Watch("w1", "ban phim"))

        watches = await repository.list_watches()

        assert len(watches) == 1
        assert watches[0].keyword == "ban phim"
        await repository.close()

    async def test_enabled_only_filter(self, repository):
        await repository.save_watch(Watch("on", "tai nghe", enabled=True))
        await repository.save_watch(Watch("off", "ban phim", enabled=False))

        assert [
            w.watch_id for w in await repository.list_watches(enabled_only=True)
        ] == ["on"]
        assert len(await repository.list_watches()) == 2
        await repository.close()

    async def test_delete_reports_whether_it_removed_anything(self, repository):
        await repository.save_watch(Watch("w1", "tai nghe"))

        assert await repository.delete_watch("w1") is True
        assert await repository.delete_watch("w1") is False
        await repository.close()

    async def test_a_watch_with_no_ceiling_round_trips_as_none(self, repository):
        await repository.save_watch(
            Watch("w1", "tai nghe", max_price=None, min_rating=None)
        )
        [stored] = await repository.list_watches()

        assert stored.max_price is None
        assert stored.min_rating is None
        await repository.close()


class TestNotificationBookkeeping:
    async def test_a_new_deal_is_notifiable_once(self, repository):
        candidate = (100, 1, "w1", 80.0, 200_000)

        assert await repository.unnotified([candidate]) == [(100, 1, "w1")]
        assert await repository.unnotified([candidate]) == []
        await repository.close()

    async def test_a_further_price_drop_is_notifiable_again(self, repository):
        await repository.unnotified([(100, 1, "w1", 80.0, 200_000)])

        assert await repository.unnotified([(100, 1, "w1", 85.0, 150_000)]) == [
            (100, 1, "w1")
        ]
        await repository.close()

    async def test_a_price_rise_is_not_re_announced(self, repository):
        await repository.unnotified([(100, 1, "w1", 80.0, 200_000)])

        assert await repository.unnotified([(100, 1, "w1", 70.0, 250_000)]) == []
        await repository.close()

    async def test_the_same_listing_under_two_watches_is_tracked_separately(
        self, repository
    ):
        await repository.unnotified([(100, 1, "w1", 80.0, 200_000)])

        assert await repository.unnotified([(100, 1, "w2", 80.0, 200_000)]) == [
            (100, 1, "w2")
        ]
        await repository.close()

    async def test_nothing_in_nothing_out(self, repository):
        assert await repository.unnotified([]) == []
        await repository.close()


class TestSchema:
    async def test_opening_twice_is_safe(self, repository):
        await repository.open()
        await repository.open()

        assert (await repository.stats())["snapshots"] == 0
        await repository.close()

    async def test_creates_its_parent_directory(self, tmp_path):
        from shopee_hunter.storage.repository import Repository

        repository = Repository(tmp_path / "nested" / "deep" / "db.sqlite3")
        await repository.open()

        assert (tmp_path / "nested" / "deep" / "db.sqlite3").is_file()
        await repository.close()

    async def test_stats_counts_every_table(self, repository, product_factory):
        await repository.record_snapshots([product_factory()])
        await repository.save_watch(Watch("w1", "tai nghe"))

        stats = await repository.stats()

        assert set(stats) == {"watches", "products", "snapshots", "notified"}
        await repository.close()


def _at(product, moment):
    """Re-date an observation (dataclasses.replace, spelled out for readability)."""
    from dataclasses import replace

    return replace(product, captured_at=moment)


def _with_price(product, price):
    from dataclasses import replace

    return replace(product, price=price)
