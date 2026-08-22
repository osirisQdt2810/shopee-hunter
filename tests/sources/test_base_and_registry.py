"""The adapter seam: rate limiting, retry policy, the fallback chain, the registry."""

from __future__ import annotations

import asyncio

import pytest

from shopee_hunter.core.errors import (
    ConfigError,
    SourceAuthRequired,
    SourceBlocked,
    SourceUnavailable,
)
from shopee_hunter.core.models import Product, SearchQuery
from shopee_hunter.core.rate_limit import AsyncTokenBucket
from shopee_hunter.sources.base import SourceAdapter, SourceChain
from shopee_hunter.sources.registry import (
    SOURCE_REGISTRY,
    available_sources,
    build_chain,
    build_source,
    register_source,
)


class RecordingAdapter(SourceAdapter):
    """An adapter that answers however the test tells it to, and counts its calls."""

    id = "recording"
    label = "recording"
    supports_flash_sale = True

    def __init__(self, settings, *, limiter=None, behaviour=None, available=True):
        # An effectively unlimited bucket unless a test supplies one: these tests are about
        # policy, not about waiting.
        super().__init__(
            settings, limiter=limiter or AsyncTokenBucket(rate=1e6, burst=1000)
        )
        self.behaviour = behaviour or []
        self.calls = 0
        self._available = available

    async def is_available(self) -> bool:
        return self._available

    async def _do_search(self, query: SearchQuery) -> list[Product]:
        self.calls += 1
        step = (
            self.behaviour[min(self.calls - 1, len(self.behaviour) - 1)]
            if self.behaviour
            else []
        )
        if isinstance(step, Exception):
            raise step
        return list(step)

    async def _do_fetch_item(self, item_id: int, shop_id: int) -> Product:
        raise SourceUnavailable("not implemented in the test double", source=self.id)


@pytest.fixture
def query() -> SearchQuery:
    return SearchQuery("tai nghe", limit=10)


def _skip_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the retry backoff instant.

    Captures the real ``asyncio.sleep`` first — a replacement that calls the (already
    patched) ``asyncio.sleep`` recurses until the stack runs out, which is how the first
    version of this helper "failed" the retry tests.
    """
    real_sleep = asyncio.sleep

    async def instant(_seconds: float) -> None:
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", instant)


class CountingBucket(AsyncTokenBucket):
    """A bucket that never makes anyone wait but records every token taken."""

    def __init__(self) -> None:
        super().__init__(rate=1e6, burst=1000)
        self.acquisitions = 0

    async def acquire(self, cost: float = 1.0) -> float:
        self.acquisitions += 1
        return await super().acquire(cost)


class PagingAdapter(SourceAdapter):
    """An adapter whose one ``search`` issues several requests, like the real ones do."""

    id = "paging"
    label = "paging"

    def __init__(self, settings, *, limiter=None, pages=3):
        super().__init__(settings, limiter=limiter)
        self.pages = pages

    async def _do_search(self, query: SearchQuery) -> list[Product]:
        for page in range(self.pages):
            await self._throttle(f"page {page}")
        return []

    async def _do_fetch_item(self, item_id: int, shop_id: int) -> Product:
        raise SourceUnavailable("not implemented in the test double", source=self.id)


class TestRateLimitIsPerRequest:
    """ADR-007: every outbound request pays a token, not every *operation*.

    The bug this pins was invisible at the default settings. `_guarded` took one token for a
    whole search, but a search pages: `items_per_watch = 600` makes `page_count == 10`, so
    one token bought ten back-to-back requests — about 10 req/s against a bucket configured
    for 0.5 with a burst of 4. At the default of 60 the loop runs once and the bypass leaves
    no trace, which is why only a multi-page test can catch it.
    """

    async def test_each_page_pays_its_own_token(self, settings, query):
        limiter = CountingBucket()
        adapter = PagingAdapter(settings, limiter=limiter, pages=5)

        await adapter.search(query)

        assert limiter.acquisitions == 5

    async def test_an_operation_that_makes_no_request_pays_nothing(
        self, settings, query
    ):
        """The offline fixture source must not be charged for work it does locally."""
        limiter = CountingBucket()
        adapter = PagingAdapter(settings, limiter=limiter, pages=0)

        await adapter.search(query)

        assert limiter.acquisitions == 0

    async def test_a_retried_operation_pays_again(
        self, settings, query, product_factory, monkeypatch
    ):
        """A retry re-enters the request path, so it must not ride the first token."""
        _skip_backoff(monkeypatch)
        limiter = CountingBucket()
        adapter = RecordingAdapter(
            settings,
            limiter=limiter,
            behaviour=[
                SourceUnavailable("boom", source="recording"),
                [product_factory()],
            ],
        )

        # RecordingAdapter stands in for a transport, so it charges the bucket the way a real
        # request helper does.
        original = adapter._do_search

        async def counted(q):
            await adapter._throttle("search")
            return await original(q)

        monkeypatch.setattr(adapter, "_do_search", counted)

        await adapter.search(query)

        assert limiter.acquisitions == 2


class TestGuardPolicy:
    async def test_a_transport_failure_is_retried(
        self, settings, query, product_factory, monkeypatch
    ):
        _skip_backoff(monkeypatch)
        adapter = RecordingAdapter(
            settings,
            behaviour=[
                SourceUnavailable("boom", source="recording"),
                [product_factory()],
            ],
        )

        products = await adapter.search(query)

        assert len(products) == 1
        assert adapter.calls == 2

    async def test_retries_are_bounded(self, settings, query, monkeypatch):
        _skip_backoff(monkeypatch)
        adapter = RecordingAdapter(
            settings, behaviour=[SourceUnavailable("boom", source="recording")]
        )

        with pytest.raises(SourceUnavailable):
            await adapter.search(query)

        assert adapter.calls == settings.sources.web.max_retries + 1

    async def test_a_block_is_never_retried(self, settings, query):
        """Retrying a soft block is how it becomes a hard one."""
        adapter = RecordingAdapter(
            settings, behaviour=[SourceBlocked("refused", source="recording")]
        )

        with pytest.raises(SourceBlocked):
            await adapter.search(query)

        assert adapter.calls == 1

    async def test_a_block_empties_the_bucket(self, settings, query):
        limiter = AsyncTokenBucket(rate=1e6, burst=1000)
        adapter = RecordingAdapter(
            settings,
            limiter=limiter,
            behaviour=[SourceBlocked("refused", source="recording")],
        )

        with pytest.raises(SourceBlocked):
            await adapter.search(query)

        assert limiter.bucket.delay_for() > 0, "a refusal must cost us our token budget"

    async def test_missing_credentials_are_not_retried(self, settings, query):
        adapter = RecordingAdapter(
            settings, behaviour=[SourceAuthRequired("no keys", source="recording")]
        )

        with pytest.raises(SourceAuthRequired):
            await adapter.search(query)

        assert adapter.calls == 1, "waiting cannot conjure a credential"

    async def test_flash_sale_is_empty_rather_than_an_error_when_unsupported(
        self, settings
    ):
        class NoFlash(RecordingAdapter):
            supports_flash_sale = False

        assert await NoFlash(settings).flash_sale() == []


class TestChain:
    async def test_uses_the_first_adapter_that_answers(
        self, settings, query, product_factory
    ):
        first = RecordingAdapter(settings, behaviour=[[product_factory()]])
        second = RecordingAdapter(settings, behaviour=[[product_factory(item_id=2)]])
        chain = SourceChain([first, second])

        await chain.search(query)

        assert second.calls == 0
        assert chain.last_source == "recording"

    async def test_falls_through_a_block(self, settings, query, product_factory):
        blocked = RecordingAdapter(
            settings, behaviour=[SourceBlocked("refused", source="a")]
        )
        working = RecordingAdapter(settings, behaviour=[[product_factory()]])
        chain = SourceChain([blocked, working])

        products = await chain.search(query)

        assert len(products) == 1
        assert working.calls == 1

    async def test_skips_an_unavailable_adapter_without_calling_it(
        self, settings, query, product_factory
    ):
        unavailable = RecordingAdapter(settings, available=False)
        working = RecordingAdapter(settings, behaviour=[[product_factory()]])

        await SourceChain([unavailable, working]).search(query)

        assert unavailable.calls == 0

    async def test_every_source_failing_reports_all_of_them(self, settings, query):
        chain = SourceChain(
            [
                RecordingAdapter(
                    settings, behaviour=[SourceBlocked("first refused", source="a")]
                ),
                RecordingAdapter(
                    settings, behaviour=[SourceBlocked("second refused", source="b")]
                ),
            ]
        )

        with pytest.raises(SourceBlocked) as caught:
            await chain.search(query)

        assert "first refused" in str(caught.value)
        assert "second refused" in str(caught.value)

    async def test_flash_sale_only_asks_capable_adapters(
        self, settings, product_factory
    ):
        class NoFlash(RecordingAdapter):
            supports_flash_sale = False

        incapable = NoFlash(settings)
        chain = SourceChain([incapable])

        assert await chain.flash_sale() == []
        assert incapable.calls == 0

    def test_an_empty_chain_is_a_programming_error(self):
        with pytest.raises(ValueError, match="at least one"):
            SourceChain([])


class TestRegistry:
    def test_the_real_adapters_are_registered(self):
        assert {"web", "browser", "affiliate", "fixture"} <= set(available_sources())

    def test_unknown_source_says_what_is_available(self, settings):
        with pytest.raises(ConfigError, match="registered"):
            build_source("carrier-pigeon", settings)

    def test_double_registration_of_a_different_class_is_refused(self):
        with pytest.raises(ConfigError, match="already registered"):

            @register_source("web")
            class Impostor(RecordingAdapter):
                pass

    def test_the_decorator_sets_the_id(self):
        try:

            @register_source("temporary-test-source")
            class Temporary(RecordingAdapter):
                pass

            assert Temporary.id == "temporary-test-source"
        finally:
            SOURCE_REGISTRY.pop("temporary-test-source", None)

    def test_demo_mode_forces_the_fixture_source(self, settings):
        settings.demo_mode = True
        settings.sources.order = ["web", "browser"]

        chain = build_chain(settings)

        assert [adapter.id for adapter in chain.adapters] == ["fixture"]

    def test_the_chain_shares_one_bucket_across_adapters(self, settings):
        """The rate limit bounds our traffic to Shopee, not our traffic per transport."""
        settings.demo_mode = False
        settings.sources.order = ["web", "affiliate"]

        chain = build_chain(settings)
        first, second = chain.adapters

        assert first._limiter is second._limiter

    def test_only_overrides_the_configured_order(self, settings):
        settings.demo_mode = False

        chain = build_chain(settings, only=["web"])

        assert [adapter.id for adapter in chain.adapters] == ["web"]
