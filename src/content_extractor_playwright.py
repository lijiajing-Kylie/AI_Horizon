"""Playwright-based article page rendering for JS-heavy sites.

Renders the page in headless Chromium, waits for JavaScript to execute,
then passes the rendered HTML through the same trafilatura extraction
pipeline used by ``content_extractor.py``.

Intended for sources whose article text is delivered by client-side
JavaScript (SPAs, React apps, etc.) and is invisible to a plain
``httpx`` GET.

Follows the same optional-import pattern as ``twitter_playwright.py``:
Playwright is imported lazily and the module degrades gracefully when
it is not installed.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import trafilatura

logger = logging.getLogger(__name__)

# ── Optional Playwright imports ─────────────────────────────────────────────
try:
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    async_playwright = None  # type: ignore[assignment]


def _get_proxy() -> str:
    """Resolve proxy from common env vars."""
    for key in ("PROXY", "https_proxy", "http_proxy", "all_proxy"):
        val = os.getenv(key, "").strip()
        if val:
            return val
    return ""


_PROXY = _get_proxy()

# ── Rendering constants ─────────────────────────────────────────────────────
# Extra wait after network idle to let lazy-loading JS frameworks finish.
_POST_RENDER_WAIT_MS = 3000
# Minimum rendered HTML length to consider it valid (same as content_extractor).
_MIN_HTML_LENGTH = 500

_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)


class SharedBrowserPool:
    """Shared headless Chromium for batch extraction.

    Launches once, creates an isolated context per URL (separate
    cookie/localStorage), and closes everything on exit.

    Usage::

        async with SharedBrowserPool() as pool:
            html = await pool.extract_from_url("https://example.com")
    """

    def __init__(self, headless: bool = True, channel: Optional[str] = None) -> None:
        self._headless = headless
        self._channel = channel
        self._playwright: object | None = None
        self._browser: object | None = None

    async def __aenter__(self) -> "SharedBrowserPool":
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "Playwright is not installed. Run: uv sync --extra twitter && "
                "uv run playwright install chromium"
            )
        pw = await async_playwright().start()
        self._playwright = pw
        launch_kwargs: dict = {"headless": self._headless}
        if self._channel:
            launch_kwargs["channel"] = self._channel
        if _PROXY:
            launch_kwargs["proxy"] = {"server": _PROXY}
        self._browser = await pw.chromium.launch(**launch_kwargs)
        logger.debug("SharedBrowserPool: Chromium launched (headless=%s)", self._headless)
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._browser is not None:
            await self._browser.close()
            logger.debug("SharedBrowserPool: browser closed")
        if self._playwright is not None:
            await self._playwright.stop()
            logger.debug("SharedBrowserPool: playwright stopped")

    async def extract_from_url(self, url: str, timeout: float = 30.0) -> Optional[str]:
        """Render a URL in headless Chromium and return the full HTML.

        Creates an isolated browser context, navigates to *url*, waits for
        network idle, then returns ``page.content()`` — the fully rendered
        DOM including JS-generated content.

        Returns ``None`` on any error (timeout, navigation failure, etc.).
        """
        ctx = await self._browser.new_context(
            user_agent=_BROWSER_USER_AGENT,
            viewport={"width": 1280, "height": 800},
            # Block unnecessary resources for faster page loads
        )
        page = await ctx.new_page()
        try:
            # Block images, fonts, and media to speed up rendering — we only
            # need the text content.
            await page.route(
                "**/*",
                lambda route: (
                    route.abort()
                    if route.request.resource_type in ("image", "media", "font", "stylesheet")
                    else route.continue_()
                ),
            )
            await page.goto(
                url,
                wait_until="networkidle",
                timeout=int(timeout * 1000),
            )
            # Extra wait for lazy-loading JS frameworks (React hydration, etc.)
            await page.wait_for_timeout(_POST_RENDER_WAIT_MS)
            html = await page.content()
            logger.debug("Playwright rendered %s: %d chars", url, len(html))
            return html
        except Exception as exc:
            logger.debug("Playwright rendering failed for %s: %s", url, exc)
            return None
        finally:
            await page.close()
            await ctx.close()


async def extract_full_content_browser(
    url: str,
    pool: SharedBrowserPool,
    *,
    timeout: float = 30.0,
    debug: Optional[dict] = None,
) -> Optional["ExtractedArticle"]:  # noqa: F821
    """Extract article content from a JS-rendered page via Playwright.

    Renders the page in headless Chromium, then passes the rendered HTML
    through the same trafilatura pipeline as :func:`extract_full_content`.

    Returns an ``ExtractedArticle`` or ``None``, reusing the same extraction
    helpers (image extraction, structured HTML, boilerplate stripping) from
    ``content_extractor``.
    """
    # Lazy imports to avoid circular dependency
    from .content_extractor import (  # noqa: F811
        EXTRACTOR_VERSION,
        _MIN_CONTENT_LENGTH,
        ExtractedArticle,
        _extract_images,
        _extract_structured_html,
        _strip_boilerplate_containers,
    )

    if debug is None:
        debug = {}
    debug["skip_reason"] = None
    debug["http_status"] = None

    html = await pool.extract_from_url(url, timeout=timeout)
    if not html or len(html) < _MIN_HTML_LENGTH:
        debug["skip_reason"] = "browser_html_too_short"
        logger.debug("skip url=%s reason=browser_html_too_short (len=%d)", url, len(html or ""))
        return None

    # Strip boilerplate before extraction (same as HTTP path)
    html = _strip_boilerplate_containers(html)

    try:
        text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            output_format="txt",
            favor_precision=True,
        )
    except Exception as exc:
        debug["skip_reason"] = f"trafilatura_error:{exc.__class__.__name__}"
        logger.debug("trafilatura extraction error for %s (browser): %s", url, exc)
        return None

    if not text or len(text.strip()) < _MIN_CONTENT_LENGTH:
        debug["skip_reason"] = "extract_empty_or_short"
        logger.debug("skip url=%s reason=extract_empty_or_short (browser)", url)
        return None

    cover_image, images = _extract_images(html, url)
    raw_html, display_html = _extract_structured_html(html, url)

    return ExtractedArticle(
        text=text.strip(),
        cover_image=cover_image,
        images=images,
        raw_html=raw_html,
        display_html=display_html,
        http_status=200,
        final_url=url,
    )
