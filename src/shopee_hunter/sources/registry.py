"""One registration mechanism for source adapters.

``@register_source("web")`` on the class, one import in ``sources/__init__.py`` so the
decorator actually runs, and ``build_source("web", settings)`` anywhere else. The registry is
empty until the module is imported — that is the single most common way a "Unknown source"
error happens, so it is called out in CLAUDE.md too.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Optional, TypeVar

from ..core.errors import ConfigError
from ..core.logging import get_logger
from ..core.rate_limit import AsyncTokenBucket
from ..core.settings import AppSettings
from .base import SourceAdapter, SourceChain

SOURCE_REGISTRY: dict[str, type[SourceAdapter]] = {}

_A = TypeVar("_A", bound=SourceAdapter)
_log = get_logger("sources.registry")


def register_source(source_id: str) -> Callable[[type[_A]], type[_A]]:
    """Class decorator: add an adapter to the registry under ``source_id``."""

    def decorate(cls: type[_A]) -> type[_A]:
        if source_id in SOURCE_REGISTRY and SOURCE_REGISTRY[source_id] is not cls:
            raise ConfigError(
                f"source id {source_id!r} is already registered to "
                f"{SOURCE_REGISTRY[source_id].__name__}"
            )
        cls.id = source_id
        SOURCE_REGISTRY[source_id] = cls
        return cls

    return decorate


def available_sources() -> list[str]:
    """Registered adapter ids, sorted — what ``--source`` will accept."""
    return sorted(SOURCE_REGISTRY)


def build_source(
    source_id: str,
    settings: AppSettings,
    *,
    limiter: Optional[AsyncTokenBucket] = None,
) -> SourceAdapter:
    """Instantiate one adapter by id.

    Raises:
        ConfigError: No adapter is registered under that id.
    """
    try:
        cls = SOURCE_REGISTRY[source_id]
    except KeyError:
        raise ConfigError(
            f"unknown source {source_id!r}; registered: {available_sources()}. "
            f"A new adapter must be imported in sources/__init__.py for its decorator to run."
        ) from None
    return cls(settings, limiter=limiter)


def build_chain(
    settings: AppSettings,
    *,
    only: Optional[Sequence[str]] = None,
) -> SourceChain:
    """Build the configured fallback chain (or a single-adapter chain when ``only`` is given).

    One ``AsyncTokenBucket`` is shared by every adapter in the chain: the rate limit bounds
    *our traffic to Shopee*, not our traffic per transport, so a fallback must inherit the
    penalty the previous adapter earned.
    """
    ids = list(only) if only else list(settings.sources.order)
    if settings.demo_mode:
        ids = ["fixture"]

    shared_limiter = AsyncTokenBucket(
        rate=settings.rate_limit.requests_per_second,
        burst=settings.rate_limit.burst,
    )
    adapters = [
        build_source(source_id, settings, limiter=shared_limiter) for source_id in ids
    ]
    _log.debug("source chain: %s", " -> ".join(a.id for a in adapters))
    return SourceChain(adapters)
