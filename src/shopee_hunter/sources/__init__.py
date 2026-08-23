"""Source adapters. Importing this package is what fills the registry.

Every adapter module is imported here for its ``@register_source`` side effect. Miss one and
``build_source`` raises "unknown source" for a class that is right there on disk — so this
list is load-bearing, not tidiness.
"""

from __future__ import annotations

# Registration side effects — order is irrelevant, presence is not.
from . import affiliate_api, fixture, shopee_browser, shopee_web
from .base import SourceAdapter, SourceChain
from .registry import (
    SOURCE_REGISTRY,
    available_sources,
    build_chain,
    build_source,
    register_source,
)

__all__ = [
    "SOURCE_REGISTRY",
    "SourceAdapter",
    "SourceChain",
    "available_sources",
    "build_chain",
    "build_source",
    "register_source",
]
