"""The token bucket. Clock-injected, so hours of behaviour take microseconds."""

from __future__ import annotations

import asyncio

import pytest

from shopee_hunter.core.rate_limit import AsyncTokenBucket, TokenBucket


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


class TestTokenBucket:
    def test_starts_full_so_the_first_page_is_immediate(self, clock):
        bucket = TokenBucket(rate=0.5, burst=4, monotonic=clock)

        assert [bucket.try_acquire() for _ in range(4)] == [True] * 4
        assert bucket.try_acquire() is False

    def test_refills_at_the_configured_rate(self, clock):
        bucket = TokenBucket(rate=0.5, burst=4, monotonic=clock)
        for _ in range(4):
            bucket.try_acquire()

        clock.advance(2.0)

        assert bucket.try_acquire() is True

    def test_never_accumulates_past_the_burst(self, clock):
        bucket = TokenBucket(rate=0.5, burst=4, monotonic=clock)
        clock.advance(10_000)

        assert bucket.tokens == pytest.approx(4.0)

    def test_delay_for_reports_the_wait(self, clock):
        bucket = TokenBucket(rate=0.5, burst=1, monotonic=clock)
        bucket.try_acquire()

        assert bucket.delay_for() == pytest.approx(2.0)

    def test_penalise_holds_the_bucket_empty(self, clock):
        """A block must stop us asking, not slow us down slightly."""
        bucket = TokenBucket(rate=0.5, burst=4, monotonic=clock)

        bucket.penalise(120.0)

        assert bucket.delay_for() == pytest.approx(122.0)
        clock.advance(60)
        assert bucket.try_acquire() is False
        clock.advance(70)
        assert bucket.try_acquire() is True

    @pytest.mark.parametrize(("rate", "burst"), [(0, 4), (-1, 4), (0.5, 0)])
    def test_rejects_nonsense_configuration(self, rate, burst):
        with pytest.raises(ValueError):
            TokenBucket(rate=rate, burst=burst)


class TestAsyncTokenBucket:
    async def test_concurrent_callers_cannot_all_pass_the_same_tokens(self):
        """Without the lock, N coroutines each see enough tokens and all proceed."""
        slept: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        bucket = AsyncTokenBucket(rate=1000.0, burst=2, sleep=fake_sleep)

        await asyncio.gather(*(bucket.acquire() for _ in range(6)))

        # Four of the six had to wait: the first two consumed the burst.
        assert len(slept) >= 4

    async def test_reports_how_long_it_made_the_caller_wait(self):
        async def fake_sleep(seconds: float) -> None:
            return None

        bucket = AsyncTokenBucket(rate=1.0, burst=1, sleep=fake_sleep)
        await bucket.acquire()

        waited = await bucket.acquire()

        assert waited > 0
