"""Shared fixtures, and the rule that keeps the default suite honest: no network.

The offline tier must be deterministic (ADR-008). The cheapest way to guarantee that is to
make opening a socket an error unless the test is marked ``live`` — otherwise an accidental
real request turns into a test that passes on a good day and flakes on a bad one, which is
worse than no test.
"""

from __future__ import annotations

import socket
import sys
from collections.abc import Iterator
from datetime import UTC
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_create_connection = socket.create_connection

# Loopback and non-IP families stay open. asyncio builds its event loop out of a socketpair,
# sqlite's WAL and Qt's internals use local sockets, and breaking those would be blocking the
# wrong thing — what must be impossible is reaching the internet.
_ALLOWED_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", ""})


class BlockedNetworkError(RuntimeError):
    """Raised when an offline test tries to reach the network."""


def _is_local(address: object) -> bool:
    if isinstance(address, tuple) and address:
        return str(address[0]) in _ALLOWED_HOSTS
    # AF_UNIX (a path) and anything unrecognised: not an outbound internet connection.
    return True


@pytest.fixture(autouse=True)
def no_network(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Refuse outbound connections for every test not marked ``live``.

    Patching ``connect`` rather than ``socket.socket`` is deliberate: replacing the socket
    class itself breaks asyncio's own event-loop construction, so the guard has to sit at the
    point where a test would actually reach the network.
    """
    if request.node.get_closest_marker("live"):
        yield
        return

    def guarded_connect(self, address):  # type: ignore[no-untyped-def]
        if not _is_local(address):
            raise BlockedNetworkError(
                f"blocked outbound connection to {address!r}. The default suite is offline — "
                f"use a fixture, respx, or mark the test @pytest.mark.live (which excludes it "
                f"from the default run)."
            )
        return _real_connect(self, address)

    def guarded_connect_ex(self, address):  # type: ignore[no-untyped-def]
        if not _is_local(address):
            raise BlockedNetworkError(f"blocked outbound connection to {address!r}")
        return _real_connect_ex(self, address)

    def guarded_create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
        if not _is_local(address):
            raise BlockedNetworkError(f"blocked outbound connection to {address!r}")
        return _real_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    yield


@pytest.fixture
def settings():
    """Default settings, forced offline and demo-mode for tests."""
    from shopee_hunter.core.settings import AppSettings

    return AppSettings.model_validate(
        {
            "demo_mode": True,
            "sources": {"order": ["fixture"]},
            "scan": {
                "min_discount_pct": 5.0,
                "genuine_only": False,
                "items_per_watch": 20,
            },
        }
    )


@pytest.fixture
def now():
    """A fixed instant: 12.12 at 14:30 UTC — a mega-sale day inside a flash slot.

    Every time-dependent test uses this rather than the wall clock, so the suite behaves the
    same in July as it does in December.
    """
    from datetime import datetime

    return datetime(2026, 12, 12, 14, 30, tzinfo=UTC)


@pytest.fixture
def repository(tmp_path: Path):
    """A repository on a throwaway SQLite file."""
    from shopee_hunter.storage.repository import Repository

    return Repository(tmp_path / "test.sqlite3")


@pytest.fixture
def product_factory(now):
    """Build products without repeating twelve keyword arguments per test."""
    from shopee_hunter.core.models import Money, Product, Shop

    def build(
        item_id: int = 1,
        shop_id: int = 100,
        name: str = "Tai nghe Bluetooth Test",
        price: int = 200_000,
        before: int | None = 400_000,
        claimed: int = 50,
        rating: float | None = 4.7,
        rating_count: int = 500,
        sold: int = 1_000,
        official: bool = True,
        flash: bool = False,
    ) -> Product:
        return Product(
            item_id=item_id,
            shop_id=shop_id,
            name=name,
            price=Money(price),
            price_before_discount=Money(before) if before else None,
            claimed_discount_pct=claimed,
            rating=rating,
            rating_count=rating_count,
            sold_count=sold,
            shop=Shop(shop_id=shop_id, name="Test Shop", is_official=official),
            is_flash_sale=flash,
            captured_at=now,
        )

    return build


@pytest.fixture
def snapshot_factory(now):
    """A run of historical snapshots at a steady price."""
    from datetime import timedelta

    from shopee_hunter.core.models import Money, PriceSnapshot

    def build(
        price: int,
        *,
        count: int = 12,
        every_days: int = 5,
        item_id: int = 1,
        shop_id: int = 100,
        flash: bool = False,
    ) -> list[PriceSnapshot]:
        return [
            PriceSnapshot(
                item_id=item_id,
                shop_id=shop_id,
                price=Money(price),
                observed_at=now - timedelta(days=(index + 1) * every_days),
                is_flash_sale=flash,
            )
            for index in range(count)
        ]

    return build
