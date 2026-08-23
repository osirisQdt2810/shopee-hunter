"""LIVE tests: real requests to the real Shopee. Run with ``pytest -m live``.

These are excluded from the default suite and from CI (ADR-008). Their contract is unusual and
deliberate: **a refusal is a pass.** Shopee turning us away is normal operation, and what these
tests actually verify is that the adapter *says so with the right typed error* rather than
returning an empty list that the UI would render as "no deals".

What fails a live test:
  * a ``ParseError`` — Shopee changed its wire format and ``sources/parse.py`` must be fixed;
  * a successful response we cannot turn into usable products;
  * an untyped exception leaking out of an adapter.
"""

from __future__ import annotations

import pytest

from shopee_hunter.core.errors import (
    ParseError,
    SourceAuthRequired,
    SourceBlocked,
    SourceUnavailable,
)
from shopee_hunter.core.models import SearchQuery
from shopee_hunter.core.settings import AppSettings

pytestmark = pytest.mark.live

KEYWORD = "tai nghe bluetooth"


@pytest.fixture
def live_settings() -> AppSettings:
    """Real settings, but never demo mode — that would make these tests meaningless."""
    from shopee_hunter.core.settings import AppPaths

    settings = AppSettings.load(user=AppPaths.settings_file())
    settings.demo_mode = False
    settings.scan.items_per_watch = 20
    return settings


class TestWebSourceLive:
    async def test_search_either_returns_products_or_says_why_not(self, live_settings):
        from shopee_hunter.sources.shopee_web import ShopeeWebSource

        live_settings.sources.web.enabled = True
        adapter = ShopeeWebSource(live_settings)
        try:
            products = await adapter.search(SearchQuery(KEYWORD, limit=20))
        except (SourceBlocked, SourceAuthRequired) as exc:
            # The expected outcome without cookies. The assertion is that the message is
            # actionable — a refusal the user cannot act on is as bad as a silent failure.
            assert str(exc)
            pytest.skip(f"Shopee refused the web source (a valid outcome): {exc}")
        except SourceUnavailable as exc:
            pytest.skip(f"transport unavailable: {exc}")
        finally:
            await adapter.aclose()

        assert products, "a 200 response with no products means the wire format moved"
        for product in products:
            assert product.name
            assert product.item_id > 0 and product.shop_id > 0
            assert product.price.amount >= 0
            assert 0 <= product.claimed_discount_pct <= 100
            assert product.url.startswith("https://")

    async def test_a_parse_error_is_never_acceptable(self, live_settings):
        """Separated from the test above so a wire-format change fails rather than skips."""
        from shopee_hunter.sources.shopee_web import ShopeeWebSource

        live_settings.sources.web.enabled = True
        adapter = ShopeeWebSource(live_settings)
        try:
            await adapter.search(SearchQuery(KEYWORD, limit=20))
        except ParseError as exc:
            pytest.fail(
                f"Shopee's wire format changed: {exc}\n"
                f"Re-capture the fixture and fix sources/parse.py:\n"
                f"  python scripts/capture_fixture.py --keyword {KEYWORD!r}"
            )
        except (SourceBlocked, SourceAuthRequired, SourceUnavailable):
            pass  # not what this test is about
        finally:
            await adapter.aclose()


class TestBrowserSourceLive:
    async def test_search_through_a_real_browser(self, live_settings):
        """Needs the ``[browser]`` extra and, on shopee.vn, a signed-in profile.

        Observed 2026-08-23: an anonymous profile is redirected to
        ``/verify/traffic/error`` and every search call answers ``error: 90309999``. That is
        a ``SourceAuthRequired``, and this test skips on it — the *classification* is what is
        being verified, and it is asserted below.
        """
        pytest.importorskip(
            "playwright", reason="the browser source needs the [browser] extra"
        )
        from shopee_hunter.sources.shopee_browser import ShopeeBrowserSource

        live_settings.sources.browser.enabled = True
        live_settings.sources.browser.headless = True
        adapter = ShopeeBrowserSource(live_settings)
        try:
            products = await adapter.search(SearchQuery(KEYWORD, limit=20))
        except SourceAuthRequired as exc:
            assert (
                "sign" in str(exc).lower() or "log" in str(exc).lower()
            ), "a risk-control refusal must tell the user what to do about it"
            pytest.skip(f"browser profile is not signed in (a valid outcome): {exc}")
        except (SourceBlocked, SourceUnavailable) as exc:
            pytest.skip(f"browser source refused/unavailable: {exc}")
        finally:
            await adapter.aclose()

        assert products
        assert all(product.price.amount >= 0 for product in products)


class TestEndToEndLive:
    async def test_a_full_scan_records_history_even_when_nothing_qualifies(
        self, live_settings, tmp_path
    ):
        """The pipeline's real contract: every observation feeds the next scan's verdicts."""
        from shopee_hunter.services.scanner import Scanner
        from shopee_hunter.sources import build_chain
        from shopee_hunter.storage.repository import Repository

        repository = Repository(tmp_path / "live.sqlite3")
        chain = build_chain(live_settings)
        scanner = Scanner(live_settings, chain, repository)
        try:
            result = await scanner.scan_keyword(KEYWORD, limit=20)
        finally:
            await chain.aclose()
            await repository.close()

        assert not result.broken, f"a code-level failure occurred: {result.failures}"
        if result.blocked:
            pytest.skip(f"every source refused (a valid outcome): {result.refusals}")

        assert (
            result.source_used
        ), "a successful scan must record which adapter answered"
        assert result.snapshots_written == result.products_seen
