"""Sale Hunter — a Windows + macOS desktop app that hunts real Shopee discounts.

Layer map (imports go one way only; see .claude/CLAUDE.md):
    core/    pure logic — no Qt, no httpx, no sqlite, no I/O
    sources/ every way of reading Shopee, behind one adapter contract
    storage/ local SQLite: price history is load-bearing, not a cache
    services/ orchestration: scan, schedule, notify
    gui/     Qt + QML only; holds no business rule
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
