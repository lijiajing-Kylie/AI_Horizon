"""ByteDance Seed tech blog scraper.

Seed (https://seed.bytedance.com/zh/blog) is ByteDance's official AI research
and product blog. It is a Modern.js SPA with server-side rendering — the blog
list and individual article content are embedded as ``window._ROUTER_DATA``
JSON in the HTML. No RSS feed or public API is available.

This scraper extracts the SSR JSON via plain HTTP (no Playwright needed) and
parses articles from both the list page and individual detail pages.

Notes:
    - Article detail pages include full HTML in both Chinese (ContentZh) and
      English (ContentEn). The scraper prefers Chinese content and falls back
      to English.
    - The ``fetch_limit`` config controls how many articles are fetched from
      the list page before an optional detail fetch (which is heavier).
    - Published dates use millisecond epoch timestamps from the SSR data.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urljoin

import httpx

from ..models import ContentItem, SourceType, ByteDanceNewsConfig
from .base import BaseScraper

logger = logging.getLogger(__name__)

_BLOG_LIST_URL = "https://seed.bytedance.com/zh/blog"
_ARTICLE_BASE = "https://seed.bytedance.com/zh/blog/"

# Regex patterns for extracting SSR data from HTML
_ROUTER_DATA_RE = re.compile(
    r"window\._ROUTER_DATA\s*=\s*(\{.+?\});?\s*</script>",
    re.DOTALL,
)


class ByteDanceSeedScraper(BaseScraper):
    """Scrape ByteDance Seed tech blog articles via SSR JSON extraction."""

    SOURCE_TYPE = SourceType.BYTEDANCE_NEWS

    def __init__(self, config: ByteDanceNewsConfig, http_client: httpx.AsyncClient):
        super().__init__(config.model_dump(), http_client)
        self.bt_config = config

    # ── public API ───────────────────────────────────────────────

    async def fetch(self, since: datetime) -> List[ContentItem]:
        """Fetch ByteDance Seed blog articles published since ``since``."""
        if not self.bt_config.enabled:
            return []

        logger.info("Fetching ByteDance Seed blog (since %s)", since.isoformat())

        # 1. Fetch the blog listing page to get article metadata
        articles = await self._fetch_article_list(since)
        if not articles:
            logger.info("No new articles found on blog list page")
            return []

        logger.debug("Blog list returned %d candidate articles", len(articles))

        # 2. Optionally fetch individual article detail pages for full content
        if self.bt_config.fetch_details:
            articles = await self._enrich_with_details(articles, since)

        return articles

    # ── list page ────────────────────────────────────────────────

    async def _fetch_article_list(self, since: datetime) -> List[ContentItem]:
        """Fetch the blog list page and extract recent articles."""
        try:
            resp = await self.client.get(
                _BLOG_LIST_URL,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
                follow_redirects=True,
                timeout=30,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("Failed to fetch blog list: %s", exc)
            return []

        # Parse the ROUTER_DATA JSON from the response
        router_data = self._extract_router_data(resp.text)
        if router_data is None:
            logger.warning("Could not extract _ROUTER_DATA from blog list page")
            return []

        # Navigate: loaderData → "(locale$)/blog/page" → article_list
        loader = router_data.get("loaderData", {})
        blog_page_key = self._find_blog_list_key(loader)
        if not blog_page_key:
            logger.warning("Blog list key not found in loaderData (keys: %s)", list(loader.keys()))
            return []

        blog_data = loader[blog_page_key]
        article_list = blog_data.get("article_list", [])

        all_items: List[ContentItem] = []
        for entry in article_list:
            item = self._entry_to_contentitem(entry, since)
            if item:
                all_items.append(item)

        # Respect fetch_limit
        limit = self.bt_config.fetch_limit
        if limit and len(all_items) > limit:
            all_items = all_items[:limit]

        logger.debug("Parsed %d articles from blog list (limit=%s)", len(all_items), limit)
        return all_items

    def _find_blog_list_key(self, loader: dict) -> Optional[str]:
        """Find the blog list page key inside loaderData.

        The key depends on the locale route parameter pattern,
        e.g. ``(locale$)/blog/page`` or similar.
        """
        for key in loader:
            if "/blog" in key and "page" in key and "id" not in key:
                return key
        return None

    def _entry_to_contentitem(
        self, entry: dict, since: datetime
    ) -> Optional[ContentItem]:
        """Convert a single list-page entry to a ContentItem."""
        meta = entry.get("ArticleMeta") or {}
        sub_zh = entry.get("ArticleSubContentZh") or {}
        sub_en = entry.get("ArticleSubContentEn") or {}

        # --- Published date (millisecond epoch) ---
        pub_ms = meta.get("PublishDate")
        if not pub_ms:
            return None
        published_at = datetime.fromtimestamp(pub_ms / 1000, tz=timezone.utc)

        # Skip articles outside our time window
        if published_at < since:
            return None

        # --- Title (prefer Chinese) ---
        title = sub_zh.get("Title") or sub_en.get("Title") or ""
        title = title.strip()
        if not title:
            return None

        # --- URL ---
        title_key = sub_zh.get("TitleKey") or sub_en.get("TitleKey") or ""
        if title_key:
            article_url = urljoin(_ARTICLE_BASE, title_key)
        else:
            # Fallback: use the article ID
            article_id = meta.get("ArticleID") or meta.get("ID")
            article_url = urljoin(_ARTICLE_BASE, str(article_id)) if article_id else ""

        if not article_url:
            return None

        # --- Stable ID ---
        raw_id = str(meta.get("ArticleID") or meta.get("ID") or hash(title))
        native_id = hashlib.md5(raw_id.encode()).hexdigest()[:12]

        # --- Cover image ---
        cover = sub_zh.get("Cover") or sub_en.get("Cover") or ""

        # --- Research area / category ---
        research_areas = meta.get("ResearchArea") or []
        categories = [ra.get("ResearchAreaNameZh") or ra.get("ResearchAreaName", "") for ra in research_areas]

        # --- Abstract / summary ---
        summary = sub_zh.get("Abstract") or sub_en.get("Abstract") or ""

        return ContentItem(
            id=self._generate_id("bytedance_news", "article", native_id),
            source_type=SourceType.BYTEDANCE_NEWS,
            title=title,
            url=article_url,
            rss_summary=summary,  # scraper-provided abstract
            raw_html=None,  # Will be enriched if fetch_details is True
            author="ByteDance Seed",
            published_at=published_at,
            cover_image=cover,
            metadata={
                "language": "zh",
                "categories": categories,
                "is_pinned": meta.get("IsPinned", False),
                "source_url": _BLOG_LIST_URL,
            },
        )

    # ── detail pages ─────────────────────────────────────────────

    async def _enrich_with_details(
        self, items: List[ContentItem], since: datetime
    ) -> List[ContentItem]:
        """Fetch individual article detail pages for full HTML content."""
        enriched: List[ContentItem] = []
        for item in items:
            detail = await self._fetch_detail(str(item.url))
            if detail:
                # Merge detail content into the item
                if "content_zh" in detail:
                    item.raw_html = detail["content_zh"]
                    item.metadata["content_en"] = detail.get("content_en", "")
                elif "content_en" in detail:
                    item.raw_html = detail["content_en"]
                else:
                    item.raw_html = None
            enriched.append(item)

        return enriched

    async def _fetch_detail(self, url: str) -> Optional[dict]:
        """Fetch an individual article page and extract its content."""
        try:
            resp = await self.client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
                follow_redirects=True,
                timeout=30,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.debug("Failed to fetch detail page %s: %s", url, exc)
            return None

        router_data = self._extract_router_data(resp.text)
        if router_data is None:
            return None

        loader = router_data.get("loaderData", {})
        detail_key = self._find_detail_key(loader)
        if not detail_key:
            return None

        page_data = loader[detail_key].get("data", {})
        article = page_data.get("article") or {}

        result = {}
        content_zh = article.get("ContentZh") or ""
        content_en = article.get("ContentEn") or ""

        if content_zh:
            result["content_zh"] = self._clean_html_content(content_zh)
        if content_en:
            result["content_en"] = self._clean_html_content(content_en)

        # Also grab the sub article data for author/journal info
        sub = article.get("SubArticle") or {}
        sub_meta = sub.get("ArticleMeta") or {}
        if sub_meta.get("Author"):
            result["author"] = sub_meta["Author"]

        return result

    def _find_detail_key(self, loader: dict) -> Optional[str]:
        """Find the article detail page key inside loaderData."""
        for key in loader:
            if "/blog" in key and "id" in key:
                return key
        return None

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _extract_router_data(html: str) -> Optional[dict]:
        """Extract and parse the ``window._ROUTER_DATA`` JSON from HTML."""
        m = _ROUTER_DATA_RE.search(html)
        if not m:
            return None
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse _ROUTER_DATA JSON: %s", exc)
            return None

    @staticmethod
    def _clean_html_content(html: str) -> str:
        """Remove inline styles from HTML content for cleaner storage."""
        # Remove most inline styles (keep structural HTML)
        cleaned = re.sub(r'\s*style="[^"]*"', "", html)
        return cleaned.strip()
