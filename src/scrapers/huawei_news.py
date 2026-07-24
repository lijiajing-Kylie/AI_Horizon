"""Huawei News Center scraper using Playwright.

Huawei's news page (https://www.huawei.com/cn/news) is a Sitecore CMS +
Webpack SPA with no public RSS feed or API — all content is rendered
client-side. This scraper uses Playwright to render the page and extract
articles from the DOM.
"""

import hashlib
import logging
import os
import random
from datetime import datetime, timezone
from typing import List, Optional

from ..models import ContentItem, SourceType, HuaweiNewsConfig
from .base import BaseScraper

logger = logging.getLogger(__name__)

# Optional Playwright imports — gracefully degraded if not installed
try:
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def _get_proxy() -> str:
    """Resolve proxy from common env vars (PROXY, https_proxy, http_proxy, all_proxy)."""
    for key in ("PROXY", "https_proxy", "http_proxy", "all_proxy"):
        val = os.getenv(key, "").strip()
        if val:
            return val
    return ""


PROXY = _get_proxy()

# How many "scroll-to-load-more" rounds to attempt at most
MAX_SCROLL_ROUNDS = 3
# Delay between page actions (seconds)
ACTION_DELAY = (1.5, 3.0)


class HuaweiNewsScraper(BaseScraper):
    """Scrape Huawei News Center articles via Playwright DOM extraction."""

    SOURCE_TYPE = SourceType.HUAWEI_NEWS
    BASE_URL = "https://www.huawei.com/cn/news"

    def __init__(self, config: HuaweiNewsConfig, http_client=None):
        """Initialize the scraper.

        Args:
            config: HuaweiNewsConfig instance with scraper settings
            http_client: Not used (Playwright manages its own connection);
                         kept for API compatibility with BaseScraper
        """
        super().__init__(config.model_dump(), http_client)
        self.hw_config = config

    async def fetch(self, since: datetime) -> List[ContentItem]:
        """Fetch Huawei News articles published since ``since``.

        Args:
            since: Only fetch articles published after this time

        Returns:
            List of ContentItem objects
        """
        if not self.hw_config.enabled:
            return []

        if not PLAYWRIGHT_AVAILABLE:
            logger.warning(
                "Playwright not installed. Run: uv sync --extra twitter && uv run playwright install chromium"
            )
            return []

        target_url = self.hw_config.url or self.BASE_URL

        logger.info("Fetching Huawei News from %s (since %s)", target_url, since.isoformat())

        all_items: List[ContentItem] = []
        seen_urls: set[str] = set()

        async with async_playwright() as p:
            launch_kwargs: dict = {"headless": True, "channel": "chromium"}
            if PROXY:
                launch_kwargs["proxy"] = {"server": PROXY}

            browser = await p.chromium.launch(**launch_kwargs)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                color_scheme="light",
            )

            page = await context.new_page()

            # Block heavy resources (we only need rendered DOM)
            async def _route_handler(route):
                rtype = route.request.resource_type
                if rtype in ("image", "media", "font", "stylesheet"):
                    await route.abort()
                else:
                    url = route.request.url.lower()
                    if any(
                        k in url
                        for k in (
                            "google-analytics",
                            "doubleclick",
                            "googletagmanager",
                            "tiqcdn",
                        )
                    ):
                        await route.abort()
                    else:
                        await route.continue_()

            await page.route("**/*", _route_handler)

            try:
                await page.goto(target_url, wait_until="networkidle", timeout=30000)
            except Exception as exc:
                logger.warning("Initial page load timed out, retrying: %s", exc)
                try:
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                except Exception as exc2:
                    logger.error("Failed to load Huawei News page: %s", exc2)
                    await browser.close()
                    return []

            # Give the SPA time to hydrate and render article cards
            await page.wait_for_timeout(5000)

            # Try extraction, scrolling for more content
            for round_num in range(MAX_SCROLL_ROUNDS + 1):
                articles = await self._extract_articles(page)
                if not articles:
                    logger.debug("No articles found on current page state (round %d)", round_num)
                    if round_num == 0:
                        # On first round, dump a DOM snippet for debugging
                        try:
                            snippet = await page.evaluate(
                                "document.querySelector('.content-list-box')?.innerHTML?.substring(0, 500) || "
                                "document.querySelector('.video-list')?.innerHTML?.substring(0, 500) || "
                                "'no news container found'"
                            )
                            logger.debug("News container snippet: %s", snippet)
                        except Exception:
                            pass
                    break

                logger.debug("Round %d: extracted %d article cards", round_num, len(articles))

                for article in articles:
                    article_url = article.get("url", "").strip()
                    if not article_url:
                        continue

                    # Deduplicate by URL
                    if article_url in seen_urls:
                        continue
                    seen_urls.add(article_url)

                    item = self._article_to_contentitem(article, since)
                    if item:
                        all_items.append(item)

                if len(all_items) >= self.hw_config.fetch_limit:
                    logger.info("Reached fetch limit (%d), stopping", self.hw_config.fetch_limit)
                    break

                # Try to load more content via scroll or button click
                loaded_more = await self._load_more(page)
                if not loaded_more:
                    logger.debug("No more content to load after round %d", round_num)
                    break

                # Small pause for new content to render
                await page.wait_for_timeout(2000)

            await browser.close()

        logger.info("Huawei News: fetched %d articles total", len(all_items))
        return all_items

    async def _extract_articles(self, page) -> List[dict]:
        """Extract article data from the rendered DOM.

        Returns:
            List of dicts with keys: url, title, date, thumbnail, thumbnailAlt
        """
        extract_script = """() => {
            const articles = [];

            // Strategy 1: look for known Sitecore rendered cards
            // The X-JsRender template renders items in .video-list-item
            const cards = document.querySelectorAll('.video-list-item');

            for (const card of cards) {
                const link = card.querySelector('a.c-box, a[href*="/news/"]');
                const img = card.querySelector('img');
                const titleEl = card.querySelector('h4, .js-text-dot-cn, [class*="title"]');
                const timeEl = card.querySelector('.time, [class*="time"], [class*="date"]');

                const href = link ? link.getAttribute('href') : '';
                const url = href && !href.startsWith('http')
                    ? (href.startsWith('//') ? 'https:' + href
                       : href.startsWith('/') ? 'https://www.huawei.com' + href
                       : 'https://www.huawei.com/' + href)
                    : href;

                articles.push({
                    url: url,
                    title: titleEl ? (titleEl.textContent || '').trim() : '',
                    date: timeEl ? (timeEl.textContent || '').trim() : '',
                    thumbnail: img ? img.getAttribute('src') || img.getAttribute('data-src') || '' : '',
                    thumbnailAlt: img ? img.getAttribute('alt') || '' : '',
                });
            }

            if (articles.length > 0) return articles;

            // Strategy 2: broader card detection
            const allLinks = document.querySelectorAll('a[href*="/news/"]');
            for (const link of allLinks) {
                const parent = link.closest('li, div[class*="item"], div[class*="card"], article') || link;
                const img = parent.querySelector('img');
                const titleEl = parent.querySelector('h1, h2, h3, h4, [class*="title"]');
                const timeEl = parent.querySelector('[class*="time"], [class*="date"], time');

                const href = link.getAttribute('href') || '';
                const url = href && !href.startsWith('http')
                    ? (href.startsWith('//') ? 'https:' + href
                       : href.startsWith('/') ? 'https://www.huawei.com' + href
                       : 'https://www.huawei.com/' + href)
                    : href;

                const title = titleEl ? (titleEl.textContent || '').trim() : '';
                if (!title || !url) continue;

                articles.push({
                    url: url,
                    title: title,
                    date: timeEl ? (timeEl.textContent || '').trim() : '',
                    thumbnail: img ? img.getAttribute('src') || img.getAttribute('data-src') || '' : '',
                    thumbnailAlt: img ? img.getAttribute('alt') || '' : '',
                });
            }

            return articles;
        }"""

        try:
            return await page.evaluate(extract_script)
        except Exception as exc:
            logger.debug("DOM extraction failed: %s", exc)
            return []

    async def _load_more(self, page) -> bool:
        """Attempt to load more articles by scrolling or clicking.

        Returns:
            True if new content was likely loaded, False otherwise
        """
        try:
            # Check for a "load more" button first
            load_more = await page.query_selector(
                '.newsroom-more a, [class*="load-more"], [class*="show-more"], button:has-text("更多"), '
                'a:has-text("加载更多"), .pagination a.next'
            )
            if load_more:
                # Check if it's disabled
                is_disabled = await load_more.get_attribute("disabled")
                has_disabled_class = await load_more.evaluate(
                    "el => el.classList.contains('disabled') || el.classList.contains('v')"
                )
                if not is_disabled and not has_disabled_class:
                    await load_more.click()
                    logger.debug("Clicked 'load more' button")
                    return True

            # Fall back to scroll-to-bottom
            before_height = await page.evaluate("document.body.scrollHeight")
            await page.evaluate(f"window.scrollBy(0, {random.randint(500, 1000)})")
            await page.wait_for_timeout(1500)
            after_height = await page.evaluate("document.body.scrollHeight")

            if after_height > before_height:
                logger.debug("Scrolled: content height grew from %d to %d", before_height, after_height)
                return True

            return False
        except Exception as exc:
            logger.debug("Load-more attempt failed: %s", exc)
            return False

    def _article_to_contentitem(self, article: dict, since: datetime) -> Optional[ContentItem]:
        """Convert a parsed article dict to a ContentItem.

        Args:
            article: Article dict from _extract_articles
            since: Filter threshold

        Returns:
            ContentItem or None if the article is outside the time window
        """
        url = article.get("url", "").strip()
        title = article.get("title", "").strip()
        date_str = article.get("date", "").strip()

        if not url or not title:
            return None

        # Parse date
        published_at = self._parse_date(date_str)
        if published_at is None:
            # Can't filter by date — still return it
            published_at = datetime.now(timezone.utc)
        elif published_at < since:
            return None

        # Generate a stable ID from the URL
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]

        return ContentItem(
            id=self._generate_id("huawei_news", "article", url_hash),
            source_type=SourceType.HUAWEI_NEWS,
            title=title,
            url=url,
            content=None,  # Will be populated by content_extractor later
            author="Huawei News Center",
            published_at=published_at,
            cover_image=article.get("thumbnail", ""),
            metadata={
                "language": "zh" if "cn" in (self.hw_config.url or self.BASE_URL) else "en",
                "category": self.hw_config.category or "",
                "thumbnail_alt": article.get("thumbnailAlt", ""),
                "source_url": self.hw_config.url or self.BASE_URL,
            },
        )

    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        """Parse a date string from Huawei News into a timezone-aware datetime.

        Handles formats like:
        - "2024-01-15"
        - "2024-01-15 10:30"
        - "2024/01/15"
        - "2024年1月15日"
        - "15 Jan 2024"
        """
        if not date_str:
            return None

        date_str = date_str.strip()

        # Try ISO-like formats
        for fmt in (
            "%Y-%m-%d",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d",
            "%Y/%m/%d %H:%M",
        ):
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        # Try Chinese date format: 2024年1月15日
        try:
            cleaned = date_str.replace("年", "-").replace("月", "-").replace("日", "").strip()
            dt = datetime.strptime(cleaned, "%Y-%m-%d")
            return dt.replace(tzinfo=timezone.utc)
        except (ValueError, IndexError):
            pass

        # Try dateutil as a last resort
        try:
            from dateutil import parser as dateparser

            dt = dateparser.parse(date_str)
            if dt:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
        except ImportError:
            pass
        except Exception:
            pass

        logger.warning("Could not parse date string: '%s'", date_str)
        return None
