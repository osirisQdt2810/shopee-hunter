"""Browser-backed adapter: read the response Shopee's own page already received.

The technique here changed once, for a reason worth recording, because the obvious approach
does not work.

**What does not work:** opening the real page and calling ``fetch('/api/v4/search/...')`` from
inside it. Cookies and TLS fingerprint are then genuinely the browser's — and Shopee still
answers 403, because its front end signs every API call with a per-request header computed by
its own JavaScript. ``fetch`` from the console does not carry that signature, so the request
looks like a bot *inside* a real browser. Headless and headful both fail identically, which is
the tell: the block is not fingerprinting, it is a missing signature.

**What works:** never make the request at all. Navigate to the page a shopper would open
(``/search?keyword=…``), let Shopee's own JavaScript issue its own signed request, and read the
response off the wire with Playwright's response listener. The signature problem disappears
because we are not the one signing.

Cost of that reliability: Playwright is a ~150 MB download, so it stays an optional
``[browser]`` extra, imported lazily — the app must start fine without it (ADR-004). The
profile is persistent and the user logs into it themselves; we never see a password.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote_plus

from ..core.errors import (
    BrowserNotInstalled,
    SourceAuthRequired,
    SourceBlocked,
    SourceUnavailable,
)
from ..core.models import Product, SearchQuery
from ..core.rate_limit import AsyncTokenBucket
from ..core.settings import AppPaths, AppSettings
from .base import SourceAdapter
from .parse import parse_flash_sale_response, parse_item, parse_search_response
from .registry import register_source

PAGE_SIZE = 60

# Page URLs whose own JavaScript calls the API we want. Navigating to these is the whole
# trick: Shopee signs its own request, and we read the answer.
SEARCH_PAGE = "/search?keyword={keyword}&page={page}"
PRODUCT_PAGE = "/product/{shop_id}/{item_id}"
FLASH_SALE_PAGE = "/flash_sale"

# Substrings identifying the API responses worth capturing on each page.
SEARCH_API = "/api/v4/search/search_items"
PRODUCT_API = "/api/v4/pdp/get_pc"
FLASH_API = "/api/v4/flash_sale/"

# Paths Shopee redirects an unwelcome visitor to. Observed live: an anonymous session asking
# for /search lands on `/verify/traffic/error?...&is_logged_in=false&type=4`, the page still
# renders its own <title> (so a title check proves nothing), and zero product cards appear.
# Detecting the URL is what turns a mystifying timeout into "log in once".
INTERSTITIAL_MARKERS = (
    "/verify/traffic",
    "/verify/captcha",
    "/buyer/login",
    "/verify/ivs",
)


@register_source("browser")
class ShopeeBrowserSource(SourceAdapter):
    """Drives a real browser profile; issues API calls from inside the page."""

    label = "Real browser (your session)"
    requires_credentials = True
    supports_flash_sale = True

    def __init__(
        self,
        settings: AppSettings,
        *,
        limiter: Optional[AsyncTokenBucket] = None,
    ) -> None:
        super().__init__(settings, limiter=limiter)
        self.config = settings.sources.browser
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None

    @property
    def profile_dir(self) -> Path:
        return self.config.profile_dir or AppPaths.browser_profile_dir()

    async def is_available(self) -> bool:
        """Enabled *and* importable — a missing extra must not fail the whole chain."""
        if not self.config.enabled:
            return False
        try:
            import playwright.async_api  # noqa: F401
        except ImportError:
            self.log.info("browser source is enabled but playwright is not installed")
            return False
        return True

    # -- browser lifecycle ------------------------------------------------------
    async def _ensure_page(self) -> Any:
        """Open (once) a persistent context on the storefront and return its page.

        Persistent, not incognito: the whole point is that the user's login survives between
        runs. The first launch is visible by default so they *can* log in.
        """
        if self._page is not None:
            return self._page

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserNotInstalled(
                'the browser source needs the optional extra: pip install -e ".[browser]" '
                "&& playwright install chromium"
            ) from exc

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        try:
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                channel=(
                    None if self.config.channel == "chromium" else self.config.channel
                ),
                headless=self.config.headless,
                locale=f"{self.settings.storefront.language}-VN",
                viewport={"width": 1440, "height": 900},
            )
        except Exception as exc:  # playwright raises its own Error type
            await self._shutdown()
            raise SourceUnavailable(
                f"could not launch {self.config.channel}: {exc}. Install the browser with "
                f"`playwright install chromium`, or set sources.browser.channel.",
                source=self.id,
            ) from exc

        self._page = (
            self._context.pages[0]
            if self._context.pages
            else await self._context.new_page()
        )
        self._page.set_default_timeout(self.config.nav_timeout_seconds * 1000)
        try:
            await self._page.goto(
                f"https://{self.domain}/", wait_until="domcontentloaded"
            )
        except Exception as exc:
            await self._shutdown()
            raise SourceUnavailable(
                f"could not open https://{self.domain}: {exc}", source=self.id
            ) from exc
        return self._page

    async def _shutdown(self) -> None:
        for closer in (
            getattr(self._context, "close", None),
            getattr(self._playwright, "stop", None),
        ):
            if closer is not None:
                try:
                    await closer()
                except Exception:
                    self.log.debug("browser teardown raised; ignoring", exc_info=True)
        self._playwright = self._context = self._page = None

    async def aclose(self) -> None:
        await self._shutdown()

    # -- capturing the page's own API traffic ----------------------------------
    async def _capture(self, page_path: str, api_marker: str) -> dict[str, Any]:
        """Open a page and return the first JSON body it fetches from ``api_marker``.

        Args:
            page_path: Path on the storefront, e.g. ``/search?keyword=tai+nghe&page=0``.
            api_marker: Substring identifying the API response to keep.

        Raises:
            SourceBlocked: The page loaded but never issued that request within the timeout,
                or answered it with an error. Usually an interstitial or a layout change.
            SourceAuthRequired: The page redirected to a login wall.
            SourceUnavailable: Navigation itself failed.
        """
        page = await self._ensure_page()
        loop = asyncio.get_running_loop()
        captured: asyncio.Future[dict[str, Any]] = loop.create_future()

        async def on_response(response: Any) -> None:
            if api_marker not in response.url or captured.done():
                return
            if response.status != 200:
                if not captured.done():
                    captured.set_exception(
                        SourceBlocked(
                            f"Shopee answered its own request with HTTP {response.status}",
                            source=self.id,
                        )
                    )
                return
            try:
                body = await response.json()
            except Exception:
                return
            if isinstance(body, dict) and not captured.done():
                captured.set_result(body)

        page.on("response", on_response)
        url = f"https://{self.domain}{page_path}"
        try:
            await page.goto(url, wait_until="domcontentloaded")
            # Shopee lazy-loads the result grid, so a bare `goto` can settle before the
            # search request is issued. A scroll is what a shopper does anyway.
            await page.mouse.wheel(0, 1600)
            self._assert_not_interstitial(page.url)
            payload = await asyncio.wait_for(
                captured, timeout=self.config.nav_timeout_seconds
            )
        except TimeoutError as exc:
            self._assert_not_interstitial(page.url)
            raise SourceBlocked(
                f"{url} loaded but issued no {api_marker} request within "
                f"{self.config.nav_timeout_seconds:.0f}s (interstitial, captcha, or a page "
                f"layout change)",
                source=self.id,
            ) from exc
        except SourceBlocked:
            raise
        except Exception as exc:  # playwright raises its own Error type
            raise SourceUnavailable(
                f"navigation to {url} failed: {exc}", source=self.id
            ) from exc
        finally:
            page.remove_listener("response", on_response)

        return payload

    def _assert_not_interstitial(self, current_url: str) -> None:
        """Raise an actionable error if Shopee bounced us to a verification wall.

        Checked both immediately after navigation and again on timeout: the redirect can
        happen before the page would have issued its search request (so the wait would
        otherwise expire) or after it.
        """
        if any(marker in current_url for marker in INTERSTITIAL_MARKERS):
            raise SourceAuthRequired(
                f"Shopee redirected to its verification wall ({current_url}). This storefront "
                f"refuses anonymous search from this network. Run once with "
                f"sources.browser.headless = false, sign into Shopee in the window that "
                f"opens, then re-run — the profile at {self.profile_dir} is reused.",
                source=self.id,
            )

    # -- adapter contract -------------------------------------------------------
    async def _do_search(self, query: SearchQuery) -> list[Product]:
        collected: list[Product] = []
        for page_index in range(query.page_count):
            path = SEARCH_PAGE.format(
                keyword=quote_plus(query.keyword), page=page_index
            )
            # Filters go on the page URL, not on an API call we construct: the page's own JS
            # turns them into whatever the API currently expects.
            if query.max_price is not None:
                path += f"&maxPrice={query.max_price.amount}"
            if query.min_price is not None:
                path += f"&minPrice={query.min_price.amount}"
            if query.official_only:
                path += "&officialMall=true"

            payload = await self._capture(path, SEARCH_API)
            products = parse_search_response(
                payload, currency=self.currency, source=self.id
            )
            collected.extend(products)
            if payload.get("nomore") or not products or len(collected) >= query.limit:
                break
        return collected[: query.limit]

    async def _do_fetch_item(self, item_id: int, shop_id: int) -> Product:
        payload = await self._capture(
            PRODUCT_PAGE.format(shop_id=shop_id, item_id=item_id), PRODUCT_API
        )
        from .parse import check_api_error

        check_api_error(payload, source=self.id)
        data = payload.get("data") or {}
        item = data.get("item") if isinstance(data, dict) else None
        return parse_item(item or data, currency=self.currency, source=self.id)

    async def _do_flash_sale(self, limit: int) -> list[Product]:
        payload = await self._capture(FLASH_SALE_PAGE, FLASH_API)
        return parse_flash_sale_response(
            payload, currency=self.currency, source=self.id
        )[:limit]
