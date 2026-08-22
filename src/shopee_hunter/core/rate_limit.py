"""Self-throttling. Not optional, and deliberately conservative.

This app is a personal deal watcher. Two things follow from that: Shopee should barely
notice it, and the user's IP should never get flagged — a blocked account is a far worse
outcome than a missed discount. So every request passes a token bucket whose defaults
assume "one interested human", not "a crawler".

Pure and clock-injectable: the bucket takes a ``monotonic`` callable, so tests exercise
hours of behaviour in microseconds. ``AsyncTokenBucket`` wraps it for the async callers and
is the only thing here that touches asyncio.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

# One request every 2s sustained, with a small burst for the first page of a search.
DEFAULT_RATE_PER_SECOND = 0.5
DEFAULT_BURST = 4


@dataclass
class TokenBucket:
    """Classic token bucket: ``rate`` tokens accrue per second, capped at ``burst``.

    Args:
        rate: Sustained requests per second.
        burst: Maximum tokens that can accumulate (the size of an allowed spike).
        monotonic: Clock source; injected so tests need no sleeping.
    """

    rate: float = DEFAULT_RATE_PER_SECOND
    burst: int = DEFAULT_BURST
    monotonic: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        if self.rate <= 0:
            raise ValueError("rate must be positive")
        if self.burst < 1:
            raise ValueError("burst must be at least 1")
        self._tokens = float(self.burst)
        self._updated = self.monotonic()

    def _refill(self) -> None:
        now = self.monotonic()
        elapsed = max(0.0, now - self._updated)
        self._updated = now
        self._tokens = min(float(self.burst), self._tokens + elapsed * self.rate)

    @property
    def tokens(self) -> float:
        """Tokens available right now (refills as a side effect, like a real bucket)."""
        self._refill()
        return self._tokens

    def try_acquire(self, cost: float = 1.0) -> bool:
        """Take ``cost`` tokens if available. Never blocks."""
        self._refill()
        if self._tokens >= cost:
            self._tokens -= cost
            return True
        return False

    def delay_for(self, cost: float = 1.0) -> float:
        """Seconds until ``cost`` tokens would be available (0.0 if they already are)."""
        self._refill()
        if self._tokens >= cost:
            return 0.0
        return (cost - self._tokens) / self.rate

    def penalise(self, seconds: float) -> None:
        """Empty the bucket and hold it empty for ``seconds``.

        Called when the site pushes back (``SourceBlocked``): the correct response to "you
        are asking too much" is to stop asking, not to retry the same second.
        """
        self._refill()
        self._tokens = -abs(seconds) * self.rate


class AsyncTokenBucket:
    """Async facade over :class:`TokenBucket`, safe for concurrent callers.

    The lock matters: without it, N coroutines each see enough tokens and all proceed,
    which is exactly the burst the bucket exists to prevent.
    """

    def __init__(
        self,
        rate: float = DEFAULT_RATE_PER_SECOND,
        burst: int = DEFAULT_BURST,
        *,
        sleep: Callable[[float], object] = asyncio.sleep,
    ) -> None:
        self._bucket = TokenBucket(rate=rate, burst=burst)
        self._lock = asyncio.Lock()
        self._sleep = sleep

    @property
    def bucket(self) -> TokenBucket:
        return self._bucket

    async def acquire(self, cost: float = 1.0) -> float:
        """Wait until ``cost`` tokens are available, then take them.

        Returns:
            How long the caller was made to wait, so the adapter can log real throttling.
        """
        async with self._lock:
            waited = 0.0
            while True:
                delay = self._bucket.delay_for(cost)
                if delay <= 0.0:
                    self._bucket.try_acquire(cost)
                    return waited
                await self._sleep(delay)  # type: ignore[misc]
                waited += delay

    def penalise(self, seconds: float) -> None:
        self._bucket.penalise(seconds)
