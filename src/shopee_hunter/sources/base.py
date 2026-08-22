"""The one seam every Shopee request passes through.

An adapter describes *one request against one transport*. It does not decide how often to
ask, how long to wait, or what to do when refused — those belong here, in the base class, so
a new transport cannot forget them and one token bucket really does bound all outbound
traffic (ADR-007).

The contract is small on purpose: ``search``, ``fetch_item``, ``flash_sale``. Adding the
official API, a browser, or another marketplace means one subclass, not a caller change.
"""

from __future__ import annotations

import abc
import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import ClassVar, Optional, TypeVar

from ..core.errors import (
    ParseError,
    SourceAuthRequired,
    SourceBlocked,
    SourceError,
    SourceUnavailable,
)
from ..core.logging import get_logger
from ..core.models import Currency, Product, SearchQuery
from ..core.rate_limit import AsyncTokenBucket
from ..core.settings import AppSettings

T = TypeVar("T")

# How long the bucket stays empty after the site pushes back. Long enough that we stop being
# interesting; short enough that a flash slot is not written off entirely.
BLOCK_PENALTY_SECONDS = 120.0


class SourceAdapter(abc.ABC):
    """Base class for every transport that can read Shopee.

    Subclasses implement the ``_do_*`` methods and get rate limiting, retry, backoff, block
    penalties and logging for free. They must never catch their own transport errors into an
    empty result — raise the typed error and let the chain decide (ADR-004).

    Class attributes:
        id: Registry id, also what ``--source`` accepts on the command line.
        label: Human name for the UI.
        requires_credentials: Whether the adapter is useless without user-supplied secrets.
        supports_flash_sale: Whether ``flash_sale()`` is meaningful for this transport.
    """

    id: ClassVar[str] = ""
    label: ClassVar[str] = ""
    requires_credentials: ClassVar[bool] = False
    supports_flash_sale: ClassVar[bool] = False

    def __init__(
        self,
        settings: AppSettings,
        *,
        limiter: Optional[AsyncTokenBucket] = None,
    ) -> None:
        self.settings = settings
        self.currency = Currency(settings.storefront.currency)
        self.domain = settings.storefront.domain
        self._limiter = limiter or AsyncTokenBucket(
            rate=settings.rate_limit.requests_per_second,
            burst=settings.rate_limit.burst,
        )
        self._semaphore = asyncio.Semaphore(max(1, settings.rate_limit.max_concurrent))
        self.log = get_logger(f"sources.{self.id or type(self).__name__}")

    # -- the public contract ----------------------------------------------------
    async def search(self, query: SearchQuery) -> list[Product]:
        """Find listings matching ``query``. Rate-limited and retried."""
        return await self._guarded(
            lambda: self._do_search(query), f"search {query.keyword!r}"
        )

    async def fetch_item(self, item_id: int, shop_id: int) -> Product:
        """Fetch one listing's current state (used to refresh a watched item's price)."""
        return await self._guarded(
            lambda: self._do_fetch_item(item_id, shop_id), f"item {shop_id}_{item_id}"
        )

    async def flash_sale(self, limit: int = 60) -> list[Product]:
        """Fetch the current flash-sale batch.

        Returns an empty list for transports that cannot serve it, rather than raising —
        "this adapter has no flash-sale endpoint" is a capability fact, not a failure.
        """
        if not self.supports_flash_sale:
            return []
        return await self._guarded(lambda: self._do_flash_sale(limit), "flash sale")

    async def is_available(self) -> bool:
        """Cheap local check: are this adapter's prerequisites satisfied?

        Deliberately does *not* make a request — it answers "should the chain bother with
        this adapter", and asking the site that question would itself cost a request.
        """
        return True

    async def aclose(self) -> None:
        """Release transport resources. Safe to call more than once.

        Deliberately concrete and empty: most adapters hold nothing to release (the fixture
        source holds a path), and forcing every subclass to write an empty override would be
        ceremony that teaches people to write empty overrides.
        """

    # -- what subclasses implement ---------------------------------------------
    @abc.abstractmethod
    async def _do_search(self, query: SearchQuery) -> list[Product]: ...

    @abc.abstractmethod
    async def _do_fetch_item(self, item_id: int, shop_id: int) -> Product: ...

    async def _do_flash_sale(self, limit: int) -> list[Product]:
        """Override when ``supports_flash_sale`` is True."""
        raise NotImplementedError

    # -- the shared machinery ---------------------------------------------------
    async def _throttle(self, what: str) -> None:
        """Pay one token for one outbound request. Every request path must call this.

        Deliberately per-REQUEST rather than per-operation (ADR-007). ``_guarded`` used to
        take the single token for a whole ``search``, but a search is not one request: both
        the web and browser adapters loop over ``query.page_count`` pages, and the affiliate
        adapter pages until it has ``query.limit`` items. One token then bought ten HTTP
        requests fired back to back — roughly 10 req/s against a bucket configured for 0.5,
        which is exactly the burst signature the bucket exists to suppress. At the default
        ``items_per_watch`` the loop runs once, so the bypass was invisible.

        Adapters that make no request (the fixture source) simply never call this, which is
        why the limiter cannot be charged for offline work.
        """
        waited = await self._limiter.acquire()
        if waited > 0.5:
            self.log.debug("throttled %.1fs before %s", waited, what)

    async def _guarded(self, operation: Callable[[], Awaitable[T]], what: str) -> T:
        """Run one adapter operation with bounded retry, concurrency cap and block penalty.

        The rate-limit token is *not* taken here — ``_throttle`` charges one per request, and
        an operation may issue several. This method owns everything that is genuinely
        per-operation: the semaphore, the retry loop, and the penalty on a block.

        Retry policy, and why it is this timid: Shopee converts persistent retries of a soft
        block into a hard one. So ``SourceBlocked`` is **never** retried — it empties the
        bucket instead — and only transport-level failures get a second chance. A retried
        operation re-enters the request path, so it pays a fresh token.

        Raises:
            SourceBlocked: The site refused us (bucket penalised, no retry).
            SourceUnavailable: Transport failed and the retries were exhausted.
            SourceAuthRequired: Credentials are missing (no retry — waiting cannot help).
        """
        attempts = max(1, self.settings.sources.web.max_retries + 1)
        backoff = self.settings.sources.web.retry_backoff_seconds
        last: Optional[SourceError] = None

        for attempt in range(1, attempts + 1):
            try:
                async with self._semaphore:
                    return await operation()
            except SourceBlocked as exc:
                self._limiter.penalise(BLOCK_PENALTY_SECONDS)
                self.log.warning(
                    "%s blocked: %s (backing off %.0fs)",
                    what,
                    exc,
                    BLOCK_PENALTY_SECONDS,
                )
                raise
            except SourceAuthRequired:
                raise
            except SourceUnavailable as exc:
                last = exc
                if attempt >= attempts:
                    break
                delay = backoff * attempt
                self.log.info(
                    "%s failed (%s); retry %d/%d in %.0fs",
                    what,
                    exc,
                    attempt,
                    attempts - 1,
                    delay,
                )
                await asyncio.sleep(delay)

        assert last is not None  # only reachable via the SourceUnavailable path
        raise last

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.id!r} domain={self.domain!r}>"


class SourceChain:
    """Tries adapters in configured order until one answers.

    This is the honest response to a site that sometimes refuses: a `SourceBlocked` from the
    first transport is a reason to try the next one, not a reason to tell the user there are
    no deals. The chain records which adapter answered (``last_source``) so a fallback can
    never quietly hide a broken primary.
    """

    def __init__(self, adapters: Sequence[SourceAdapter]) -> None:
        if not adapters:
            raise ValueError("a source chain needs at least one adapter")
        self.adapters = list(adapters)
        self.last_source: Optional[str] = None
        self.log = get_logger("sources.chain")

    async def search(self, query: SearchQuery) -> list[Product]:
        return await self._first_answer(
            lambda a: a.search(query), f"search {query.keyword!r}"
        )

    async def fetch_item(self, item_id: int, shop_id: int) -> Product:
        return await self._first_answer(
            lambda a: a.fetch_item(item_id, shop_id), f"item {shop_id}_{item_id}"
        )

    async def flash_sale(self, limit: int = 60) -> list[Product]:
        capable = [a for a in self.adapters if a.supports_flash_sale]
        if not capable:
            return []
        return await SourceChain(capable)._first_answer(
            lambda a: a.flash_sale(limit), "flash sale"
        )

    async def _first_answer(
        self, call: Callable[[SourceAdapter], Awaitable[T]], what: str
    ) -> T:
        errors: list[str] = []
        for adapter in self.adapters:
            if not await adapter.is_available():
                errors.append(f"{adapter.id}: not configured")
                continue
            try:
                result = await call(adapter)
            except (
                SourceBlocked,
                SourceUnavailable,
                SourceAuthRequired,
                ParseError,
            ) as exc:
                # ParseError is in this list on purpose. A wire-format change in one
                # transport is precisely when the next one is worth trying: the affiliate
                # schema moving says nothing about whether site search still parses. Leaving
                # it out made the ordered chain useless in the one case it was built for,
                # and turned a single renamed field into a total scan failure.
                errors.append(f"{adapter.id}: {exc}")
                self.log.info("falling back past %s for %s", adapter.id, what)
                continue
            self.last_source = adapter.id
            return result

        raise SourceBlocked(
            f"every configured source failed for {what} — " + "; ".join(errors),
            source="chain",
        )

    async def aclose(self) -> None:
        for adapter in self.adapters:
            await adapter.aclose()
