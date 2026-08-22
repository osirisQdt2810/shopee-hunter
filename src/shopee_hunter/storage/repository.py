"""The only place the app talks to SQLite.

Async because every caller lives on the asyncio worker loop (ADR-003), and sqlite is
blocking: each method hands its work to ``asyncio.to_thread`` so a slow write cannot stall
the loop that the GUI is waiting on. The connection is opened with
``check_same_thread=False`` for exactly that reason and guarded by a lock, since
``to_thread`` gives no ordering guarantees.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Optional

from ..core.logging import get_logger
from ..core.models import Currency, Money, PriceSnapshot, Product, Watch
from . import db


def _iso(moment: datetime) -> str:
    """Serialise a timestamp as UTC ISO-8601.

    Everything stored is UTC. A naive datetime is *assumed* UTC rather than rejected, because
    the alternative is a crash deep in a scan over a timezone detail the user cannot fix.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat()


def _parse_iso(text: str) -> datetime:
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class Repository:
    """Watches, listing metadata, price history, notification bookkeeping."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.log = get_logger("storage.repository")
        self._connection: Optional[sqlite3.Connection] = None
        self._lock = asyncio.Lock()

    # -- lifecycle --------------------------------------------------------------
    async def open(self) -> None:
        if self._connection is None:
            self._connection = await asyncio.to_thread(db.connect, self.path)
            self.log.debug("database open at %s", self.path)

    async def close(self) -> None:
        if self._connection is not None:
            connection, self._connection = self._connection, None
            await asyncio.to_thread(connection.close)

    async def _run(self, func, *args):  # type: ignore[no-untyped-def]
        await self.open()
        async with self._lock:
            return await asyncio.to_thread(func, self._connection, *args)

    # -- price history ----------------------------------------------------------
    async def record_snapshots(self, products: Iterable[Product]) -> int:
        """Persist one observation per product. Idempotent per (listing, timestamp).

        Also refreshes the listing metadata row, so the UI can render a watched item's name
        and shop without another request.
        """
        products = list(products)
        if not products:
            return 0

        snapshot_rows = [
            (
                p.shop_id,
                p.item_id,
                p.price.amount,
                p.price.currency.value,
                _iso(p.captured_at),
                int(p.is_flash_sale),
            )
            for p in products
        ]
        product_rows = [
            (
                p.shop_id,
                p.item_id,
                p.name,
                p.image_url,
                p.shop.name if p.shop else "",
                p.rating,
                p.sold_count,
                _iso(p.captured_at),
            )
            for p in products
        ]

        def write(connection: sqlite3.Connection) -> int:
            written = db.executemany(
                connection,
                "INSERT OR IGNORE INTO price_snapshots "
                "(shop_id, item_id, price, currency, observed_at, is_flash_sale) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                snapshot_rows,
            )
            db.executemany(
                connection,
                "INSERT INTO products (shop_id, item_id, name, image_url, shop_name, rating, sold_count, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(shop_id, item_id) DO UPDATE SET "
                "name=excluded.name, image_url=excluded.image_url, shop_name=excluded.shop_name, "
                "rating=excluded.rating, sold_count=excluded.sold_count, last_seen=excluded.last_seen",
                product_rows,
            )
            return written

        return await self._run(write)

    async def history_for(
        self, item_id: int, shop_id: int, *, lookback_days: int = 90
    ) -> list[PriceSnapshot]:
        """Snapshots for one listing, newest first."""
        cutoff = _iso(datetime.now(UTC) - timedelta(days=lookback_days))

        def read(connection: sqlite3.Connection) -> list[PriceSnapshot]:
            rows = connection.execute(
                "SELECT * FROM price_snapshots WHERE shop_id = ? AND item_id = ? "
                "AND observed_at >= ? ORDER BY observed_at DESC",
                (shop_id, item_id, cutoff),
            ).fetchall()
            return [_row_to_snapshot(row) for row in rows]

        return await self._run(read)

    async def history_for_many(
        self, keys: Sequence[tuple[int, int]], *, lookback_days: int = 90
    ) -> dict[str, list[PriceSnapshot]]:
        """History for many listings in **one** query, keyed by ``Product.key``.

        One query rather than N: a 60-item scan doing 60 round-trips through
        ``asyncio.to_thread`` was the difference between a scan that feels instant and one
        that visibly stutters the first time it runs against a populated database.
        """
        if not keys:
            return {}
        cutoff = _iso(datetime.now(UTC) - timedelta(days=lookback_days))
        pairs = [(shop_id, item_id) for item_id, shop_id in keys]
        placeholders = ",".join("(?, ?)" for _ in pairs)
        flat: list[object] = [cutoff]
        for shop_id, item_id in pairs:
            flat.extend((shop_id, item_id))

        def read(connection: sqlite3.Connection) -> dict[str, list[PriceSnapshot]]:
            rows = connection.execute(
                "SELECT * FROM price_snapshots WHERE observed_at >= ? "
                f"AND (shop_id, item_id) IN ({placeholders}) "
                "ORDER BY observed_at DESC",
                flat,
            ).fetchall()
            grouped: dict[str, list[PriceSnapshot]] = {}
            for row in rows:
                snapshot = _row_to_snapshot(row)
                grouped.setdefault(snapshot.key, []).append(snapshot)
            return grouped

        return await self._run(read)

    async def prune_history(self, *, keep_days: int = 365) -> int:
        """Drop snapshots older than ``keep_days``; returns how many were removed."""
        cutoff = _iso(datetime.now(UTC) - timedelta(days=keep_days))

        def delete(connection: sqlite3.Connection) -> int:
            with connection:
                cursor = connection.execute(
                    "DELETE FROM price_snapshots WHERE observed_at < ?", (cutoff,)
                )
                return cursor.rowcount

        return await self._run(delete)

    # -- watches ----------------------------------------------------------------
    async def save_watch(self, watch: Watch) -> None:
        row = (
            watch.watch_id,
            watch.keyword,
            watch.max_price.amount if watch.max_price else None,
            watch.min_discount_pct,
            watch.min_rating,
            watch.min_sold,
            watch.shop_id,
            "\n".join(watch.exclude_terms),
            int(watch.official_only),
            int(watch.enabled),
            _iso(watch.created_at),
        )

        def write(connection: sqlite3.Connection) -> None:
            with connection:
                connection.execute(
                    "INSERT INTO watches (watch_id, keyword, max_price, min_discount_pct, "
                    "min_rating, min_sold, shop_id, exclude_terms, official_only, enabled, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(watch_id) DO UPDATE SET "
                    "keyword=excluded.keyword, max_price=excluded.max_price, "
                    "min_discount_pct=excluded.min_discount_pct, min_rating=excluded.min_rating, "
                    "min_sold=excluded.min_sold, shop_id=excluded.shop_id, "
                    "exclude_terms=excluded.exclude_terms, official_only=excluded.official_only, "
                    "enabled=excluded.enabled",
                    row,
                )

        await self._run(write)

    async def list_watches(self, *, enabled_only: bool = False) -> list[Watch]:
        sql = (
            "SELECT * FROM watches"
            + (" WHERE enabled = 1" if enabled_only else "")
            + " ORDER BY created_at"
        )

        def read(connection: sqlite3.Connection) -> list[Watch]:
            return [_row_to_watch(row) for row in connection.execute(sql).fetchall()]

        return await self._run(read)

    async def delete_watch(self, watch_id: str) -> bool:
        def delete(connection: sqlite3.Connection) -> bool:
            with connection:
                cursor = connection.execute(
                    "DELETE FROM watches WHERE watch_id = ?", (watch_id,)
                )
                return cursor.rowcount > 0

        return await self._run(delete)

    # -- notification bookkeeping ----------------------------------------------
    async def unnotified(
        self, candidates: Sequence[tuple[int, int, str, float, int]]
    ) -> list[tuple[int, int, str]]:
        """Filter candidates down to the ones worth telling the user about.

        A deal is *new* if we have never notified for it, or if its price has dropped further
        since we did. Re-announcing an unchanged deal every 5 minutes during a mega sale is
        how a useful notification becomes one the user mutes.

        Args:
            candidates: ``(shop_id, item_id, watch_id, score, price)`` tuples.

        Returns:
            The subset to notify, as ``(shop_id, item_id, watch_id)``.
        """
        if not candidates:
            return []

        def read(connection: sqlite3.Connection) -> list[tuple[int, int, str]]:
            fresh: list[tuple[int, int, str]] = []
            now = _iso(datetime.now(UTC))
            for shop_id, item_id, watch_id, score, price in candidates:
                row = connection.execute(
                    "SELECT price FROM notified_deals WHERE shop_id = ? AND item_id = ? AND watch_id = ?",
                    (shop_id, item_id, watch_id),
                ).fetchone()
                if row is not None and price >= int(row["price"]):
                    continue
                fresh.append((shop_id, item_id, watch_id))
                with connection:
                    connection.execute(
                        "INSERT INTO notified_deals (shop_id, item_id, watch_id, score, price, notified_at) "
                        "VALUES (?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(shop_id, item_id, watch_id) DO UPDATE SET "
                        "score=excluded.score, price=excluded.price, notified_at=excluded.notified_at",
                        (shop_id, item_id, watch_id, score, price, now),
                    )
            return fresh

        return await self._run(read)

    async def stats(self) -> dict[str, int]:
        """Counts for the UI's status strip."""

        def read(connection: sqlite3.Connection) -> dict[str, int]:
            def count(table: str) -> int:
                return int(
                    connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()[
                        "n"
                    ]
                )

            return {
                "watches": count("watches"),
                "products": count("products"),
                "snapshots": count("price_snapshots"),
                "notified": count("notified_deals"),
            }

        return await self._run(read)


def _row_to_snapshot(row: sqlite3.Row) -> PriceSnapshot:
    return PriceSnapshot(
        item_id=int(row["item_id"]),
        shop_id=int(row["shop_id"]),
        price=Money(int(row["price"]), Currency(row["currency"])),
        observed_at=_parse_iso(row["observed_at"]),
        is_flash_sale=bool(row["is_flash_sale"]),
    )


def _row_to_watch(row: sqlite3.Row) -> Watch:
    return Watch(
        watch_id=str(row["watch_id"]),
        keyword=str(row["keyword"]),
        max_price=(
            Money(int(row["max_price"])) if row["max_price"] is not None else None
        ),
        min_discount_pct=float(row["min_discount_pct"]),
        min_rating=float(row["min_rating"]) if row["min_rating"] is not None else None,
        min_sold=int(row["min_sold"]),
        shop_id=int(row["shop_id"]) if row["shop_id"] is not None else None,
        exclude_terms=tuple(t for t in str(row["exclude_terms"]).split("\n") if t),
        official_only=bool(row["official_only"]),
        enabled=bool(row["enabled"]),
        created_at=_parse_iso(row["created_at"]),
    )
