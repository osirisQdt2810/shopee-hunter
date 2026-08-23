"""SQLite schema and migrations. Plain ``sqlite3`` — no ORM.

Why no ORM: the whole persistence surface is four tables and about a dozen queries, most of
them "give me this listing's price history". An ORM would add a dependency and a mapping
layer to hide SQL that is already the clearest way to say what we mean.

Price history is **load-bearing**, not a cache: the deal engine's entire claim rests on
observed prices (ADR-005), so this file's job is to never lose a snapshot and never
double-count one.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from ..core.logging import get_logger

log = get_logger("storage.db")

SCHEMA_VERSION = 1

# One statement per element so a migration can replay a prefix of them.
_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS watches (
        watch_id          TEXT PRIMARY KEY,
        keyword           TEXT NOT NULL,
        max_price         INTEGER,
        min_discount_pct  REAL NOT NULL DEFAULT 20.0,
        min_rating        REAL,
        min_sold          INTEGER NOT NULL DEFAULT 0,
        shop_id           INTEGER,
        exclude_terms     TEXT NOT NULL DEFAULT '',
        official_only     INTEGER NOT NULL DEFAULT 0,
        enabled           INTEGER NOT NULL DEFAULT 1,
        created_at        TEXT NOT NULL
    )
    """,
    # Listing metadata we want to show without re-fetching. Separate from the snapshots so a
    # renamed listing does not rewrite its price history.
    """
    CREATE TABLE IF NOT EXISTS products (
        shop_id     INTEGER NOT NULL,
        item_id     INTEGER NOT NULL,
        name        TEXT NOT NULL,
        image_url   TEXT NOT NULL DEFAULT '',
        shop_name   TEXT NOT NULL DEFAULT '',
        rating      REAL,
        sold_count  INTEGER NOT NULL DEFAULT 0,
        last_seen   TEXT NOT NULL,
        PRIMARY KEY (shop_id, item_id)
    )
    """,
    # The price history. UNIQUE on (listing, observed_at) makes re-recording the same
    # observation idempotent, which matters because a retried scan must not fabricate a
    # second data point and shift the median.
    """
    CREATE TABLE IF NOT EXISTS price_snapshots (
        shop_id        INTEGER NOT NULL,
        item_id        INTEGER NOT NULL,
        price          INTEGER NOT NULL,
        currency       TEXT NOT NULL DEFAULT 'VND',
        observed_at    TEXT NOT NULL,
        is_flash_sale  INTEGER NOT NULL DEFAULT 0,
        UNIQUE (shop_id, item_id, observed_at)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_snapshots_listing ON price_snapshots (shop_id, item_id, observed_at DESC)",
    # What we have already told the user about, so a deal is announced once rather than at
    # every scan for as long as it lasts.
    """
    CREATE TABLE IF NOT EXISTS notified_deals (
        shop_id      INTEGER NOT NULL,
        item_id      INTEGER NOT NULL,
        watch_id     TEXT NOT NULL DEFAULT '',
        score        REAL NOT NULL,
        price        INTEGER NOT NULL,
        notified_at  TEXT NOT NULL,
        PRIMARY KEY (shop_id, item_id, watch_id)
    )
    """,
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
)


def connect(path: Path) -> sqlite3.Connection:
    """Open (creating if needed) the database and apply the schema.

    Pragmas, and why each one:
        * ``journal_mode=WAL`` — a scan writes while the UI reads; WAL stops them blocking.
        * ``foreign_keys=ON`` — off by default in sqlite, which silently ignores constraints.
        * ``busy_timeout`` — a locked database should wait, not raise, during a scan.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    migrate(connection)
    return connection


def migrate(connection: sqlite3.Connection) -> int:
    """Bring a connection's schema up to :data:`SCHEMA_VERSION`.

    Returns:
        The version now in force.
    """
    for statement in _SCHEMA:
        connection.execute(statement)
    current = _read_version(connection)
    if current != SCHEMA_VERSION:
        connection.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
        log.info("schema at version %d (was %s)", SCHEMA_VERSION, current or "new")
    return SCHEMA_VERSION


def _read_version(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    try:
        return int(row["value"]) if row else 0
    except (TypeError, ValueError):
        return 0


def executemany(connection: sqlite3.Connection, sql: str, rows: Iterable[tuple]) -> int:
    """Run a batch insert in one transaction and report how many rows landed.

    Batched deliberately: a 60-item scan is 60 snapshots, and 60 implicit transactions on a
    laptop's SSD is measurably slower than one.
    """
    batch = list(rows)
    if not batch:
        return 0
    with connection:
        cursor = connection.executemany(sql, batch)
        return cursor.rowcount
