"""WeChat MP scraper via the bundled we-mp-rss core (process-internal).

Fetches WeChat Official Account articles directly through the vendored
``src.we_mp_rss`` package — no external we-mp-rss Docker service, no HTTP
transport layer.  Requires a valid login token (see ``horizon-wxmp login``).
"""

from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime, timezone
from typing import List, Optional

from ..content_extractor import sanitize_article_html
from ..models import ContentItem, SourceType, WxMpConfig, WxMpSourceConfig
from .base import BaseScraper

logger = logging.getLogger(__name__)


def _html_to_text(html: str) -> str:
    """Strip article HTML to plain text, keeping paragraph breaks.

    we-mp-rss returns the full WeChat article body as HTML (``section``/
    ``p``/``img``); the AI stages read plain text, so convert here once at
    scrape time rather than in the extractor.
    """
    if not html or not html.strip():
        return ""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    lines = [ln.strip() for ln in soup.get_text("\n").split("\n")]
    return "\n".join(ln for ln in lines if ln)

# Special pseudo-feed (公众号精选文章) — not a real account, always skipped.
_FEATURED_FEED_ID = "MP_WXS_FEATURED_ARTICLES"


def faker_id_from_feed_id(feed_id: str) -> Optional[str]:
    """Derive the WeChat ``fakeid`` from a ``MP_WXS_<base64>`` feed_id.

    Round-trip verified against all configured Horizon feeds:
    ``faker_id = base64.b64encode(feed_id.removeprefix("MP_WXS_"))``.
    """
    if not feed_id or feed_id == _FEATURED_FEED_ID:
        return None
    try:
        b64 = feed_id.removeprefix("MP_WXS_")
        return base64.b64encode(b64.encode()).decode()
    except Exception:
        return None


def _enabled_faker_id(feed: WxMpSourceConfig) -> Optional[str]:
    """Return the faker_id for an enabled feed, or None to skip it."""
    if not feed.enabled:
        return None
    if feed.faker_id:
        return feed.faker_id
    return faker_id_from_feed_id(feed.feed_id or "")


class WxMpScraper(BaseScraper):
    """Scraper for WeChat MP articles via the bundled we-mp-rss core.

    Keeps the ``BaseScraper`` signature for orchestrator compatibility;
    ``http_client`` is unused (no network transport of our own).
    """

    def __init__(self, config: WxMpConfig, http_client=None):
        super().__init__({"wxmp": config}, http_client)
        self._cfg = config

    async def fetch(self, since: datetime) -> List[ContentItem]:
        import src.we_mp_rss
        from src.we_mp_rss.driver.success import CanGetToken

        src.we_mp_rss.init(self._cfg, self._cfg.data_dir)

        if not CanGetToken():
            logger.warning(
                "WeChat MP 未登录或登录态已过期，跳过该源。运行 `horizon-wxmp login` 后重试。"
            )
            return []

        items: List[ContentItem] = []
        for feed in self._cfg.feeds:
            faker_id = _enabled_faker_id(feed)
            if not faker_id:
                continue
            try:
                feed_items = await asyncio.to_thread(
                    self._fetch_feed_sync, feed, faker_id, since
                )
                items.extend(feed_items)
            except Exception as exc:
                logger.warning("抓取公众号 %r 失败: %s", feed.name, exc)
        return items

    def _fetch_feed_sync(
        self, feed: WxMpSourceConfig, faker_id: str, since: datetime
    ) -> List[ContentItem]:
        from src.we_mp_rss.core.wx.base import WxGather

        def collect(_art: dict) -> bool:
            return True

        wx = WxGather().Model("web")
        wx.get_Articles(
            faker_id=faker_id,
            Mps_id=feed.feed_id,
            Mps_title=feed.name,
            CallBack=collect,
            MaxPage=self._cfg.max_page,
            interval=self._cfg.gather_interval,
            Gather_Content=self._cfg.gather_content,
        )

        cutoff_ts = since.timestamp()
        items: List[ContentItem] = []
        for art in getattr(wx, "articles", []) or []:
            published_at = self._parse_publish_time(art)
            if published_at is None or published_at.timestamp() < cutoff_ts:
                continue
            items.append(self._to_content_item(art, feed, published_at))
        return items

    def _to_content_item(
        self, art: dict, feed: WxMpSourceConfig, published_at: datetime
    ) -> ContentItem:
        content = art.get("content", "") or ""
        native_id = str(art.get("id", "")) or art.get("url", "")
        # we-mp-rss 返回的是微信文章的完整 HTML 正文（已修复图片懒加载、保留
        # mmbiz.qpic.cn 图片）。这里直接由 scraper 产出 raw_content / raw_html /
        # display_html，并标记 extraction_mode="skip"，让提取阶段跳过 trafilatura：
        # trafilatura 会丢弃微信 CDN 无扩展名的图片 URL，重新提取会让详情页正文
        # 丢失配图。display_html 经 nh3 白名单清洗，正文与图片都会保留。
        raw_html = content
        display_html = sanitize_article_html(raw_html)
        return ContentItem(
            id=self._generate_id("wechat", str(feed.feed_id), native_id),
            source_type=SourceType.WECHAT,
            title=art.get("title", "Untitled"),
            url=art.get("url", ""),
            content=content,
            raw_content=_html_to_text(raw_html) or None,
            raw_html=raw_html or None,
            display_html=display_html or None,
            cover_image=art.get("pic_url", "") or None,
            rss_summary=art.get("description", ""),
            rss_content_quality="high" if content else "low",
            author=feed.name,
            published_at=published_at,
            metadata={
                "feed_name": feed.name,
                "feed_id": feed.feed_id,
                "category": feed.category or "",
                "pic_url": art.get("pic_url", ""),
                "extraction_mode": "skip",
            },
        )

    @staticmethod
    def _parse_publish_time(art: dict) -> Optional[datetime]:
        """Parse ``publish_time`` (unix seconds, int/str/float) to UTC datetime."""
        raw = art.get("publish_time", "")
        if raw is None or raw == "":
            return None
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            logger.debug("Cannot parse publish_time: %r", raw)
            return None
