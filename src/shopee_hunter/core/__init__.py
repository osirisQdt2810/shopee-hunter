"""Pure domain logic. Nothing in here imports PySide6, httpx, or sqlite3 — by rule.

That rule is enforced by `tests/test_architecture.py` and a pre-commit hook, and it is what
makes the deal engine and the sale calendar testable in microseconds with no fixtures.
"""

from __future__ import annotations

from .errors import (
    ConfigError,
    ParseError,
    SaleHunterError,
    SourceAuthRequired,
    SourceBlocked,
    SourceError,
    SourceUnavailable,
)
from .models import (
    Confidence,
    Currency,
    Deal,
    DealFlag,
    Money,
    PriceSnapshot,
    Product,
    SearchQuery,
    Shop,
    SortOrder,
    Watch,
)

__all__ = [
    "Confidence",
    "ConfigError",
    "Currency",
    "Deal",
    "DealFlag",
    "Money",
    "ParseError",
    "PriceSnapshot",
    "Product",
    "SaleHunterError",
    "SearchQuery",
    "Shop",
    "SortOrder",
    "SourceAuthRequired",
    "SourceBlocked",
    "SourceError",
    "SourceUnavailable",
    "Watch",
]
