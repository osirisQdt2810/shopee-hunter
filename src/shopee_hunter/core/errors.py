"""Typed errors for the whole app.

Why typed: "we got nothing back" and "the site refused us" must never look the same to a
caller. Shopee answers a rate-limited or bot-flagged request with an HTTP 200 and a JSON
body carrying ``error: 10``; if adapters signalled that by returning an empty list, the UI
would cheerfully report "no deals found" during the exact minutes a sale is running.
"""

from __future__ import annotations


class SaleHunterError(Exception):
    """Base class for every error this app raises on purpose."""


class ConfigError(SaleHunterError):
    """Settings are missing or contradictory (bad TOML, unknown source id, no keys)."""


class SourceError(SaleHunterError):
    """Base class for failures that come from a source adapter."""

    def __init__(self, message: str, *, source: str = "unknown") -> None:
        super().__init__(message)
        self.source = source

    def __str__(self) -> str:
        return f"[{self.source}] {super().__str__()}"


class SourceBlocked(SourceError):
    """The site actively refused us: bot detection, captcha, 403, or ``error: 10``.

    Retrying immediately makes it worse. The scanner backs off and the UI says "Shopee is
    throttling us" instead of "no results".
    """


class SourceUnavailable(SourceError):
    """Transport-level failure: DNS, timeout, connection reset, 5xx."""


class SourceAuthRequired(SourceError):
    """The transport needs credentials the user has not provided.

    Raised by the affiliate adapter with no keys and by the browser adapter when the
    persistent profile is not logged in.
    """


class ParseError(SourceError):
    """The response arrived but does not look like what we parse.

    Almost always means Shopee changed its wire format — the message names the field so the
    fix is a one-line search, and the captured fixture tells us what changed.
    """


class RateLimited(SourceError):
    """Our own token bucket refused the call (we throttled ourselves, not the site)."""


class BrowserNotInstalled(SaleHunterError):
    """The optional ``[browser]`` extra (Playwright) is not installed."""
