"""Matching a scan's results against what the user actually asked to be told about.

Split from ``Watch`` (which is a plain description of intent) and from ``deals.py`` (which
decides how *real* a discount is) because the three questions are genuinely different:

* ``Watch`` — "earbuds under 500k, at least 4 stars".
* ``deals`` — "is this -50% a real -50%?"
* here — "does this verified deal belong in *this* watch's results?"

Keeping them apart is what lets a watch's thresholds change without touching the engine, and
the engine improve without touching the watches. Pure functions, no I/O.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence

from .models import Deal, Product, Watch


def normalise(text: str) -> str:
    """Casefold and strip Vietnamese diacritics for tolerant keyword matching.

    Vietnamese product titles are written with and without diacritics interchangeably — a
    user typing "tai nghe" must match "Tai Nghe" and "tai nghé" alike, or the watchlist looks
    broken for the exact market this app targets.
    """
    decomposed = unicodedata.normalize("NFD", text.casefold())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    # đ/Đ has no combining form, so it survives NFD and needs its own mapping.
    return unicodedata.normalize("NFC", stripped).replace("đ", "d")


def _tokens(text: str) -> list[str]:
    return [token for token in re.split(r"[^\w]+", normalise(text)) if token]


def keyword_matches(product_name: str, keyword: str) -> bool:
    """Whether a listing name satisfies a watch's keyword.

    All of the keyword's tokens must appear (order-independent), which is stricter than a
    substring test and much looser than an exact phrase — the behaviour a shopper expects
    from "tai nghe bluetooth".
    """
    name = normalise(product_name)
    needles = _tokens(keyword)
    if not needles:
        return True
    return all(needle in name for needle in needles)


def excluded(product_name: str, exclude_terms: Sequence[str]) -> bool:
    """Whether any exclusion term appears in the listing name.

    Exclusions are how a watch stays usable: searching "iphone 15" on Shopee returns mostly
    cases and screen protectors, and "op lung, cuong luc" removes them in one step.
    """
    name = normalise(product_name)
    return any(normalise(term) in name for term in exclude_terms if term.strip())


def product_matches(product: Product, watch: Watch) -> bool:
    """Whether a listing satisfies a watch's hard filters (price, rating, seller, keyword).

    Note what is *not* checked here: the discount. A watch's ``min_discount_pct`` is compared
    against the engine's verified discount, not Shopee's claim, so it can only be applied
    once a ``Deal`` exists — see :func:`deal_matches`.
    """
    if not keyword_matches(product.name, watch.keyword):
        return False
    if excluded(product.name, watch.exclude_terms):
        return False
    if watch.max_price is not None and product.price.amount > watch.max_price.amount:
        return False
    if watch.shop_id is not None and product.shop_id != watch.shop_id:
        return False
    if watch.official_only and not (product.shop and product.shop.is_official):
        return False
    if watch.min_sold and product.sold_count < watch.min_sold:
        return False
    # An unrated listing fails a rating floor rather than passing it by default: "at least
    # 4 stars" cannot honestly include "no stars yet".
    #

    # guard clause on purpose: it is the seventh of seven identically-shaped filters, and
    # making only the final one read differently costs more than the line it saves.
    if watch.min_rating is not None and (  # noqa: SIM103
        not product.rating_is_credible or (product.rating or 0.0) < watch.min_rating
    ):
        return False
    return True


def deal_matches(deal: Deal, watch: Watch) -> bool:
    """Whether a verified deal belongs in this watch's results."""
    return (
        product_matches(deal.product, watch)
        and deal.true_discount_pct >= watch.min_discount_pct
    )


def assign_deals(deals: Iterable[Deal], watches: Sequence[Watch]) -> list[Deal]:
    """Tag each deal with the first enabled watch it satisfies; drop unmatched ones.

    First match rather than all matches: the same listing satisfying two overlapping watches
    is one thing the user wants to see, not two rows of the same earbuds.

    Two different empties, deliberately distinguished. **No watches supplied** means the
    caller is not filtering by watch at all (an ad-hoc search), so every deal passes through.
    **Watches supplied but all disabled** means the user turned them off, and passing
    everything through would show results they asked not to see.
    """
    if not watches:
        return list(deals)
    active = [watch for watch in watches if watch.enabled]
    if not active:
        return []

    tagged: list[Deal] = []
    for deal in deals:
        for watch in active:
            if deal_matches(deal, watch):
                tagged.append(deal.with_watch(watch.watch_id))
                break
    return tagged
