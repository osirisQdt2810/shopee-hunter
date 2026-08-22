"""Orchestration: turn a set of watches into a ranked list of verified deals.

This is the module that knows the *order* of operations, and the order is the point:

1. ask the source chain (one adapter answers; a block falls through to the next),
2. dedupe listings across watches and pages,
3. load each listing's price history in **one** query,
4. let ``core.deals`` decide what is real,
5. match against the watches' own thresholds,
6. record the new snapshots — so the next scan's verdicts are better than this one's,
7. report which deals are worth a notification.

Step 6 is why a scan that finds nothing is still valuable: it is still building the history
the engine reasons over (ADR-005).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional

from ..core.deals import rank_deals
from ..core.errors import SourceAuthRequired, SourceBlocked, SourceError
from ..core.logging import get_logger
from ..core.models import Deal, Product, SearchQuery, Watch, dedupe_products
from ..core.settings import AppSettings
from ..core.watchlist import assign_deals
from ..sources.base import SourceChain
from ..storage.repository import Repository

# Progress is reported as (done, total, label) so the UI can show a determinate bar and say
# what is being scanned; a callback rather than polling (CONVENTIONS Part 2).
ProgressCallback = Callable[[int, int, str], None]


@dataclass(slots=True)
class ScanResult:
    """Everything one scan produced, including what went wrong.

    Partial success is the normal case: three watches scanned, one blocked. The UI shows the
    deals *and* the warning — never one at the cost of the other.
    """

    deals: list[Deal] = field(default_factory=list)
    products_seen: int = 0
    snapshots_written: int = 0
    source_used: Optional[str] = None
    # Refusals and failures are tracked apart because they mean different things to a user
    # and to a developer. A refusal ("Shopee will not serve us") is a wait-or-log-in problem;
    # a failure (a ParseError, a bug) means the wire format moved and someone must fix code.
    # Merging them made a live run report "blocked" for a parse error, which sent the
    # operator waiting for a block that was never going to clear.
    refusals: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: Optional[datetime] = None

    @property
    def errors(self) -> list[str]:
        """Everything that went wrong, refusals first — for display and for logs."""
        return [*self.refusals, *self.failures]

    @property
    def duration_seconds(self) -> float:
        end = self.finished_at or datetime.now(UTC)
        return (end - self.started_at).total_seconds()

    @property
    def blocked(self) -> bool:
        """True when Shopee refused us and we got nothing — the "back off" state."""
        return bool(self.refusals) and not self.deals and self.products_seen == 0

    @property
    def broken(self) -> bool:
        """True when something failed in a way that needs a code fix, not patience."""
        return bool(self.failures)

    @property
    def genuine_deals(self) -> list[Deal]:
        return [deal for deal in self.deals if deal.is_genuine]

    def summary(self) -> str:
        parts = [
            f"{len(self.deals)} deal(s) from {self.products_seen} listing(s)",
            f"via {self.source_used or 'no source'}",
            f"in {self.duration_seconds:.1f}s",
        ]
        if self.errors:
            parts.append(f"{len(self.errors)} error(s)")
        return ", ".join(parts)


class Scanner:
    """Runs scans. One instance per app; safe to call concurrently (the chain throttles)."""

    def __init__(
        self,
        settings: AppSettings,
        chain: SourceChain,
        repository: Repository,
    ) -> None:
        self.settings = settings
        self.chain = chain
        self.repository = repository
        self.log = get_logger("services.scanner")

    async def scan_watches(
        self,
        watches: Sequence[Watch],
        *,
        progress: Optional[ProgressCallback] = None,
    ) -> ScanResult:
        """Scan every enabled watch and return one ranked, deduped result.

        Watches run sequentially, not in parallel: the token bucket would serialise them
        anyway, and sequential keeps progress honest and cancellation immediate.
        """
        result = ScanResult()
        active = [watch for watch in watches if watch.enabled]
        if not active:
            result.finished_at = datetime.now(UTC)
            return result

        products: list[Product] = []
        for index, watch in enumerate(active, start=1):
            if progress is not None:
                progress(index - 1, len(active), watch.keyword)
            try:
                found = await self.chain.search(
                    watch.to_query(limit=self.settings.scan.items_per_watch)
                )
            except asyncio.CancelledError:
                # Propagate: a cancelled scan must stop, but what we already found is still
                # recorded by the caller's `finally`.
                raise
            except (SourceBlocked, SourceAuthRequired) as exc:
                result.refusals.append(f"{watch.keyword}: {exc}")
                self.log.warning(
                    "watch %r refused; abandoning this scan", watch.keyword
                )
                # Every remaining watch would hit the same wall and burn the same penalty.
                break
            except SourceError as exc:
                result.failures.append(f"{watch.keyword}: {exc}")
                continue
            products.extend(found)

        if progress is not None:
            progress(len(active), len(active), "evaluating")

        result.source_used = self.chain.last_source
        return await self._evaluate(products, active, result)

    async def scan_keyword(
        self,
        keyword: str,
        *,
        max_price: Optional[int] = None,
        min_discount_pct: Optional[float] = None,
        limit: Optional[int] = None,
    ) -> ScanResult:
        """One ad-hoc search — what the UI's search box and ``live_check.py`` both call."""
        from ..core.models import Money

        result = ScanResult()
        query = SearchQuery(
            keyword=keyword,
            limit=limit or self.settings.scan.items_per_watch,
            max_price=Money(max_price) if max_price else None,
        )
        try:
            products = await self.chain.search(query)
        except (SourceBlocked, SourceAuthRequired) as exc:
            result.refusals.append(str(exc))
            result.finished_at = datetime.now(UTC)
            result.source_used = self.chain.last_source
            return result
        except SourceError as exc:
            result.failures.append(str(exc))
            result.finished_at = datetime.now(UTC)
            result.source_used = self.chain.last_source
            return result

        result.source_used = self.chain.last_source
        threshold = (
            min_discount_pct
            if min_discount_pct is not None
            else self.settings.scan.min_discount_pct
        )
        return await self._evaluate(products, (), result, min_discount_pct=threshold)

    async def flash_sale(self) -> ScanResult:
        """Scan the current flash-sale batch — the highest-yield request during a sale slot."""
        result = ScanResult()
        try:
            products = await self.chain.flash_sale(
                limit=self.settings.scan.items_per_watch
            )
        except (SourceBlocked, SourceAuthRequired) as exc:
            result.refusals.append(str(exc))
            result.finished_at = datetime.now(UTC)
            return result
        except SourceError as exc:
            result.failures.append(str(exc))
            result.finished_at = datetime.now(UTC)
            return result
        result.source_used = self.chain.last_source
        return await self._evaluate(products, (), result)

    # -- the shared tail of every scan -----------------------------------------
    async def _evaluate(
        self,
        products: Sequence[Product],
        watches: Sequence[Watch],
        result: ScanResult,
        *,
        min_discount_pct: Optional[float] = None,
    ) -> ScanResult:
        unique = dedupe_products(products)
        result.products_seen = len(unique)

        if unique:
            history = await self.repository.history_for_many(
                [(p.item_id, p.shop_id) for p in unique],
                lookback_days=self.settings.scan.history_lookback_days,
            )
            deals = rank_deals(
                unique,
                history,
                min_discount_pct=(
                    min_discount_pct
                    if min_discount_pct is not None
                    else self.settings.scan.min_discount_pct
                ),
                genuine_only=self.settings.scan.genuine_only,
            )
            result.deals = assign_deals(deals, watches) if watches else deals
            # Recorded AFTER evaluation, deliberately: including this observation in its own
            # baseline would make every first sighting look like a 0% discount.
            result.snapshots_written = await self.repository.record_snapshots(unique)

        result.finished_at = datetime.now(UTC)
        self.log.info("scan complete: %s", result.summary())
        return result

    async def notifiable(self, result: ScanResult) -> list[Deal]:
        """Deals the user has not already been told about, above the notify threshold."""
        if not self.settings.scan.notify_on_new_deal:
            return []
        threshold = self.settings.scan.notify_min_score
        candidates = [
            (
                deal.product.shop_id,
                deal.product.item_id,
                deal.watch_id or "",
                deal.score,
                deal.product.price.amount,
            )
            for deal in result.deals
            if deal.score >= threshold and deal.is_genuine
        ]
        fresh = set(await self.repository.unnotified(candidates))
        return [
            deal
            for deal in result.deals
            if (deal.product.shop_id, deal.product.item_id, deal.watch_id or "")
            in fresh
        ]
