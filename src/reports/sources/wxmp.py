"""WeChat MP reports source for the research-reports pipeline.

Fetches WeChat MP articles as research reports via a local we-mp-rss instance.
Registered in ``_SOURCE_REGISTRY`` when ``wxmp`` is listed in config's
``reports.sources``.

The ``/feed/{feed_id}.json`` endpoint already includes all fields needed for
a ``Report`` (title, content, published_at, channel_name), so article data is
cached during ``fetch_native_ids`` and returned directly from ``fetch_detail``
— no extra API calls needed.
"""

from __future__ import annotations

import json as json_mod
import logging
from datetime import datetime, timedelta, timezone
import re as _re
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from ...config.constants import WXMP_REPORT_DEFAULTS
from ..models import Report
from .base import ReportSourceFetcher

logger = logging.getLogger(__name__)

# ── WeChat article content-end markers ──────────────────────────────────
# WeChat MP articles append promotional blocks, recommended-reading
# sections, and reader UI chrome after the main body.  The first
# occurrence of any of these markers signals where meaningful content
# ends — everything after is footer noise.
_WEIXIN_CONTENT_END_MARKERS = [
    # WeChat's built-in recommended-reading section
    "推荐阅读",
    # Submission / contact info (common in institutional accounts)
    "投稿及任何意见可以联系",
    # Magazine subscription prompts (e.g. Tencent Research Institute)
    "如若您期待获得《互联网前沿》杂志",
    "纸质刊物获取地址",
    "纸刊获取链接",
    # WeChat share / action UI
    "👇 点个",
    # "点个"在看"" (the smart-quote variant embedded in share prompts)
    '点个"在看"',
    '点个在看',
    "分享洞见",
    "预览时标签不可点",
    "微信扫一扫可打开此内容",
    "使用完整服务",
]

# ── WeChat keyword-gated PDF detection ───────────────────────────────────
# Common pattern in Chinese WeChat MP articles where the PDF download is
# gated behind following the account and replying a keyword.  When matched,
# the fetcher adds a special ``type: wechat_keyword`` entry to ``pdf_urls``
# so the frontend can show a helpful message instead of a broken link.
#
# Detection uses a simple two-pass approach:
#   1. Extract any quoted keyword near a reply verb (回复/输入/发送/关键词)
#      handling 「」, “”, ‘’, 『』, and plain ""/'' quote styles.
#   2. Check for gating context (关注公众号 + 获取/下载 + PDF/报告).

# ── Pass 1: quoted keywords near a reply verb ──────────────────────────
# Matches: 回复「xxx」 / 回复："xxx" / 关键词：'xxx' / 输入"xxx" etc.
_QUOTED_KW_RE = _re.compile(
    # Verb + optional colon/space
    '(?:回复|输入|发送|关键词)\\s*[：:\\s]*'
    # Then one of several quote styles (capture group per style)
    '(?:'
    '"([^"]{1,40})"'           # "keyword" (ASCII double)
    '|'
    '「([^」]{1,40})」'        # 「keyword」(corner)
    '|'
    '『([^』]{1,40})』'        # 『keyword』(white corner)
    '|'
    '“([^“]{1,40})”'   # "keyword" (smart double)
    '|'
    '‘([^‘]{1,40})’'   # 'keyword' (smart single)  # noqa: RUF001 - ‘ is LEFT SINGLE QUOTATION MARK
    ')'
)

# ── Pass 2: unquoted keyword (verb + keyword + 获取/下载 + PDF) ──────
_UNQUOTED_KW_RE = _re.compile(
    '(?:回复|输入|发送)\\s*'
    '(?P<keyword>(?!关键词)[^，。、\\s"\'“”‘’'
    '「『」』]{2,30}?)'
    '\\s*(?:获取|下载|领取).*?(?:PDF|报告)'
)

# ── Gating-context: 关注XX公众号 ──────────────────────────────────────
_GATE_CONTEXT_RE = _re.compile(
    '关注\\s*(?P<account>[^，。\\s]{2,20}?)\\s*(?:公众号|微信公众号|微信)'
)


class WxMpReportConfig:
    """微信报告源配置：从 we-mp-rss 获取公众号文章作为报告。

    默认值定义在 src/config/constants.py 的 WXMP_REPORT_DEFAULTS 中。
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8001",
        account_names: Optional[List[str]] = None,
        max_age_days: int = WXMP_REPORT_DEFAULTS["max_age_days"],
        fetch_limit: int = WXMP_REPORT_DEFAULTS["fetch_limit"],
        known_feeds: Optional[Dict[str, str]] = None,
    ) -> None:
        self.base_url = base_url
        self.account_names = account_names or []
        self.max_age_days = max_age_days
        self.fetch_limit = fetch_limit
        # Fallback mapping: account name → feed_id (e.g. from config.sources.wxmp.feeds).
        self.known_feeds = known_feeds or {}


class WxMpReportFetcher(ReportSourceFetcher):
    """Fetcher for WeChat MP articles treated as research reports.

    Article data is cached from the feed listing — ``fetch_detail`` returns
    Reports from cache rather than making extra API calls.
    """

    source_name = "wxmp"

    def __init__(self, config: Optional[WxMpReportConfig] = None) -> None:
        self.cfg = config or WxMpReportConfig()
        self._base_url = self.cfg.base_url.rstrip("/")
        # Cache: account name → feed_id
        self._name_to_id: Optional[Dict[str, str]] = None
        # Cache: native_id → article dict (populated during fetch_native_ids)
        self._article_cache: Dict[str, dict] = {}

    async def _resolve_feed_ids(self, client: httpx.AsyncClient) -> Dict[str, str]:
        """Query we-mp-rss feed index to map account names to feed IDs.

        Uses the ``/feed/all.json`` endpoint (no auth required) to build the
        name → feed_id mapping from embedded feed metadata.
        """
        if self._name_to_id is not None:
            return self._name_to_id

        self._name_to_id = {}

        body: Optional[dict] = None
        url_full = f"{self._base_url}/feed/all.json?limit=100"

        # Try httpx first.
        try:
            resp = await client.get(
                f"{self._base_url}/feed/all.json",
                params={"limit": 100},
                timeout=30.0,
            )
            if resp.status_code == 503:
                logger.info("httpx got 503 for feed/all.json — falling back to raw socket")
                body = await self._fetch_json_via_socket(url_full)
            else:
                resp.raise_for_status()
                body = json_mod.loads(resp.text, strict=False)
        except httpx.ConnectError:
            logger.warning(
                "we-mp-rss not reachable at %s — skipping wxmp source",
                self._base_url,
            )
        except httpx.TimeoutException:
            logger.warning(
                "we-mp-rss at %s timed out — skipping wxmp source",
                self._base_url,
            )
        except Exception as exc:
            logger.info("httpx failed for feed/all.json (%s) — trying raw socket", exc)
            body = await self._fetch_json_via_socket(url_full)

        if body is None:
            return self._name_to_id

        for item in body.get("items", []):
            feed = item.get("feed") or {}
            mp_name = feed.get("name", "") or item.get("channel_name", "")
            mp_id = feed.get("id", "")
            if mp_name and mp_id and mp_name not in self._name_to_id:
                self._name_to_id[mp_name] = mp_id

        # Inject special feeds that are not in /feed/all.json.
        self._name_to_id["__featured__"] = "MP_WXS_FEATURED_ARTICLES"

        # Inject known feeds from config (fallback for accounts with no recent articles).
        for acct_name, acct_id in self.cfg.known_feeds.items():
            if acct_name not in self._name_to_id:
                self._name_to_id[acct_name] = acct_id

        return self._name_to_id

    async def fetch_native_ids(self, client: httpx.AsyncClient) -> List[str]:
        """Fetch article IDs from configured accounts within the time window,
        caching full article data for ``fetch_detail``.

        Also fetches the featured-articles feed (``MP_WXS_FEATURED_ARTICLES``)
        and merges its richer content into any existing cache entries that
        share the same URL — this catches articles whose ``content`` was empty
        when they were first cached from a regular feed.
        """
        name_to_id = await self._resolve_feed_ids(client)
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.cfg.max_age_days)
        cutoff_ts = cutoff.timestamp()
        all_ids: List[str] = []
        self._article_cache = {}

        for name in self.cfg.account_names:
            feed_id = name_to_id.get(name)
            if not feed_id:
                logger.warning("Unknown WeChat account %r — skipping", name)
                continue

            items = await self._fetch_feed(client, feed_id, name)
            for item in items:
                ts = self._parse_ts(item.get("updated"))
                if ts is None or ts < cutoff_ts:
                    continue

                article_id = str(item.get("id", ""))
                if not article_id:
                    continue

                self._cache_article(article_id, item, name)

                if article_id not in all_ids:
                    all_ids.append(article_id)

        # ── Featured-articles feed: always fetch, fill in missing content ──
        featured_id = name_to_id.get("__featured__")
        if featured_id:
            featured_items = await self._fetch_feed(
                client, featured_id, "__featured__"
            )
            for item in featured_items:
                ts = self._parse_ts(item.get("updated"))
                if ts is None or ts < cutoff_ts:
                    continue

                link = (item.get("link") or "").strip()
                if not link:
                    continue

                # Match an existing cache entry by URL.
                existing_id = None
                for eid, cached in self._article_cache.items():
                    if cached.get("link") == link:
                        existing_id = eid
                        break

                if existing_id:
                    # Backfill content if the cached version has none.
                    existing = self._article_cache[existing_id]
                    cached_text = self._extract_text(existing.get("content", ""))
                    featured_text = self._extract_text(item.get("content", ""))
                    if (not cached_text or len(cached_text) < 100) and (
                        featured_text and len(featured_text) >= 100
                    ):
                        existing["content"] = item.get("content", "")
                        existing["description"] = (
                            item.get("description") or existing["description"]
                        )
                        logger.debug(
                            "Backfilled content for %s from featured feed",
                            existing_id,
                        )
                        existing["is_featured"] = True
                else:
                    # New article only in featured feed → add to cache.
                    article_id = str(item.get("id", ""))
                    if article_id and article_id not in all_ids:
                        self._cache_article(
                            article_id, item, "__featured__", is_featured=True
                        )
                        all_ids.append(article_id)

        return all_ids

    async def _fetch_feed(
        self, client: httpx.AsyncClient, feed_id: str, label: str
    ) -> List[dict]:
        """Fetch one we-mp-rss feed and return its items (with httpx and
        raw-socket fallback)."""
        url = f"{self._base_url}/feed/{feed_id}.json"
        items: List[dict] = []
        try:
            resp = await client.get(
                url, params={"limit": self.cfg.fetch_limit}, timeout=8.0,
            )
            if resp.status_code == 503:
                logger.info(
                    "httpx got 503 for feed %s — falling back to raw socket", label
                )
                body = await self._fetch_json_via_socket(
                    f"{url}?limit={self.cfg.fetch_limit}"
                )
                items = body.get("items", []) if body else []
            else:
                resp.raise_for_status()
                items = json_mod.loads(resp.text, strict=False).get("items", [])
        except httpx.ConnectError:
            logger.warning(
                "we-mp-rss not reachable at %s — skipping feed %r",
                self._base_url, label,
            )
        except httpx.TimeoutException:
            logger.warning("we-mp-rss feed %r timed out — skipping", label)
        except Exception as exc:
            logger.info(
                "httpx failed for feed %s (%s) — trying raw socket", label, exc
            )
            body = await self._fetch_json_via_socket(
                f"{url}?limit={self.cfg.fetch_limit}"
            )
            items = body.get("items", []) if body else []
        return items

    def _cache_article(
        self, article_id: str, item: dict, feed_name: str,
        is_featured: bool = False,
    ) -> None:
        """Store a single article in ``_article_cache``."""
        self._article_cache[article_id] = {
            "id": article_id,
            "title": item.get("title", "Untitled"),
            "description": item.get("description") or "",
            "content": item.get("content") or "",
            "link": item.get("link", ""),
            "channel_name": item.get("channel_name") or feed_name,
            "updated": item.get("updated"),
            "image": item.get("image", ""),
            "is_featured": is_featured,
        }

    async def fetch_detail(
        self, client: httpx.AsyncClient, native_id: str
    ) -> Optional[Report]:
        """Return a Report from the article data cached in ``fetch_native_ids``.

        When the we-mp-rss ``content`` field is empty or too short, falls back
        to fetching the article URL directly and extracting body text from HTML.
        """
        article = self._article_cache.get(native_id)
        if article is None:
            logger.debug("No cached data for article %s — skip", native_id)
            return None

        published_at = self._parse_dt(article["updated"])
        if published_at is None:
            published_at = datetime.now(timezone.utc)

        content_text = self._extract_text(article["content"])
        content_fallback = False

        # Fallback: cached content too short → fetch article URL directly.
        if not content_text or len(content_text) < 100:
            fetched = await self._fetch_content_from_url(client, article.get("link", ""))
            if fetched and len(fetched) > len(content_text):
                content_text = self._clean_article_text(fetched)
                content_fallback = True

        # When content is still empty/short after fallback, it means the
        # httpx request was blocked by WeChat's anti-scraping (captcha
        # redirect).  The browser resolver (which uses Playwright with a
        # persistent profile) can still load the article and detect any
        # "回复关键词获取PDF" pattern — skip the AI relevance filter so
        # the article isn't discarded before reaching that stage.
        needs_browser = bool(
            not content_text or len(content_text) < 100
        ) if not content_fallback else False

        return Report(
            id=f"wxmp:{native_id}",
            source="wxmp",
            native_id=native_id,
            title=article["title"],
            institution=article["channel_name"],
            url=article["link"],
            summary=article["description"],
            content_text=content_text or article["description"],
            categories=[],
            published_at=published_at,
            updated_at=published_at,
            fetched_at=datetime.now(timezone.utc),
            skip_ai_filter=article.get("is_featured", False) or needs_browser,
            pdf_urls=self._build_pdf_urls(content_text, article),
        )

    @staticmethod
    def _detect_wechat_keyword(
        text: str, channel_name: str = ""
    ) -> Optional[dict]:
        """Scan *text* for patterns like "关注XX公众号，回复关键词获取PDF".

        Uses a simple two-pass approach:
        1. Extract any quoted keyword near a reply verb (「」, “”, etc.)
        2. Check for gating context (关注公众号 + 获取/下载 + PDF)

        Returns a ``dict`` suitable for ``report.pdf_urls`` when a match is
        found, or ``None`` when the text does not contain a gating pattern.

        The returned dict uses ``type: "wechat_keyword"`` following the
        established convention from ``fxbaogao.py`` (``type: "reader"``)
        for non-direct PDF entries.
        """
        if not text:
            logger.info("Empty text for channel=%r — skipping keyword detection", channel_name)
            return None
        if len(text) < 15:
            logger.info(
                "Text too short (%d chars) for channel=%r — skipping keyword detection",
                len(text), channel_name,
            )
            return None

        keyword: Optional[str] = None
        account = channel_name

        # ── Pass 1: quoted keyword near a reply verb ────────────────
        m = _QUOTED_KW_RE.search(text)
        if m:
            # One of the 5 quote-style groups will have matched.
            for g in (m.lastindex,):
                if m.lastindex is not None:
                    kw = m.group(m.lastindex)  # type: ignore[arg-type]
                    if kw:
                        keyword = kw.strip()
                        break
        else:
            # ── Pass 2: unquoted keyword + download verb ───────────
            m = _UNQUOTED_KW_RE.search(text)
            if m:
                keyword = (m.group("keyword") or "").strip()

        if not keyword:
            logger.info(
                "No wechat keyword pattern in %d chars of text, channel=%r",
                len(text), channel_name,
            )
            return None

        # ── Extract account name from full-sentence context ─────────
        m = _GATE_CONTEXT_RE.search(text)
        if m:
            acct = (m.group("account") or "").strip()
            if acct:
                account = acct

        logger.info(
            "Detected WeChat keyword gate: account=%r keyword=%r",
            account, keyword,
        )
        return {
            "name": f"微信关键词：{keyword}",
            "type": "wechat_keyword",
            "account": account,
            "keyword": keyword,
        }

    def _build_pdf_urls(self, content_text: str, article: dict) -> List[dict]:
        """Build ``pdf_urls`` list, prepending a ``wechat_keyword`` entry if
        the article text contains a keyword-gating pattern."""
        pdf_urls: List[dict] = []

        keyword_info = self._detect_wechat_keyword(
            content_text, article.get("channel_name", "")
        )
        if keyword_info:
            keyword_info["url"] = article.get("link", "")
            pdf_urls.append(keyword_info)
        else:
            # Show what the extracted content looks like at the tail
            # (the gating pattern is normally in the article footer).
            brief = article.get("title", "")[:60]
            if content_text:
                logger.info(
                    "No wechat keyword in %d-char content for %r; "
                    "last 300 chars: %r",
                    len(content_text), brief, content_text[-300:],
                )
            else:
                logger.info(
                    "Empty content_text for %r — we-mp-rss content may "
                    "be truncated or missing", brief,
                )

        return pdf_urls

    @staticmethod
    async def _fetch_content_from_url(
        client: httpx.AsyncClient, url: str
    ) -> str:
        """Fallback: fetch article URL and extract plain text via BeautifulSoup."""
        if not url:
            return ""
        try:
            resp = await client.get(url, timeout=15.0, follow_redirects=True)
            resp.raise_for_status()
        except Exception:
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()

        # WeChat MP articles: the body lives in #js_content.
        content_el = soup.select_one("#js_content")
        if content_el:
            text = content_el.get_text(separator="\n", strip=True)
            if len(text) > 100:
                return text

        # Fallback: try common article containers.
        for sel in ("article", "[class*=\"article\"]", "[class*=\"content\"]", "main"):
            els = soup.select(sel)
            if els:
                text = "\n".join(
                    el.get_text(separator="\n", strip=True) for el in els
                )
                if len(text) > 100:
                    return text

        # Last resort: body text.
        body = soup.find("body")
        if body:
            text = body.get_text(separator="\n", strip=True)
            if len(text) > 100:
                return text

        return ""

    @staticmethod
    async def _fetch_json_via_socket(url: str) -> Optional[dict]:
        """Fallback: fetch JSON via asyncio-native socket to bypass Docker
        Desktop proxy (known issue: Docker Desktop on macOS returns 503 for
        httpx/httpcore connections to localhost port-forwarding)."""
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 8001
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query

            import socket as _socket
            import asyncio
            loop = asyncio.get_running_loop()
            reader, writer = await asyncio.open_connection(host, port, family=_socket.AF_INET)
            try:
                raw_request = (
                    f"GET {path} HTTP/1.1\r\n"
                    f"Host: {host}:{port}\r\n"
                    f"User-Agent: Horizon/1.0\r\n"
                    f"Accept: application/json\r\n"
                    f"Connection: close\r\n\r\n"
                ).encode()
                writer.write(raw_request)
                await writer.drain()
                resp_data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30.0)
                content_length = 0
                for line in resp_data.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        content_length = int(line.split(b":")[1].strip())
                        break
                if content_length > 0:
                    body_bytes = await asyncio.wait_for(
                        reader.readexactly(content_length), timeout=60.0,
                    )
                else:
                    body_bytes = await reader.read()
            finally:
                writer.close()
                await writer.wait_closed()

            raw_headers = resp_data.decode("utf-8", errors="replace")
            status_line = raw_headers.split("\r\n")[0]
            if "200" not in status_line:
                logger.warning("Socket fallback got %s for %s", status_line, url)
                return None
            return json_mod.loads(body_bytes, strict=False)
        except asyncio.TimeoutError:
            logger.warning("Socket fallback timeout for %s", url)
            return None
        except Exception as exc:
            logger.warning("Socket fallback failed for %s: %s", url, exc)
            return None

    @staticmethod
    def _parse_ts(updated: object) -> Optional[float]:
        """Parse ``updated`` field to a Unix timestamp."""
        if updated is None:
            return None
        if isinstance(updated, (int, float)):
            return float(updated)
        if isinstance(updated, datetime):
            return updated.timestamp()
        if isinstance(updated, str):
            try:
                return datetime.fromisoformat(updated).timestamp()
            except (ValueError, TypeError):
                pass
            try:
                return float(updated)
            except (ValueError, TypeError):
                pass
        return None

    @staticmethod
    def _parse_dt(updated: object) -> Optional[datetime]:
        """Parse ``updated`` field to a datetime."""
        if updated is None:
            return None
        if isinstance(updated, datetime):
            return updated
        if isinstance(updated, (int, float)):
            return datetime.fromtimestamp(updated, tz=timezone.utc)
        if isinstance(updated, str):
            try:
                return datetime.fromisoformat(updated)
            except (ValueError, TypeError):
                pass
            try:
                return datetime.fromtimestamp(float(updated), tz=timezone.utc)
            except (ValueError, TypeError, OSError):
                pass
        return None

    @staticmethod
    def _extract_text(html: str) -> str:
        """Strip HTML tags to get clean plain text.

        Removes common UI/reader noise from WeChat article HTML before
        extracting text, then applies post-extraction cleanup for known
        patterns (novel-reader chrome, footer promotions, etc.).
        """
        import re as _re

        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")

        # Remove known noise elements from the DOM.
        for selector in (
            # Novel-reader / article-renderer UI chrome
            "svg", "noscript", "iframe",
            "[class*=\"novel\"]", "[class*=\"reader\"]",
            "[class*=\"read_\"]", "[id*=\"novel\"]", "[id*=\"reader\"]",
            # Navigation / toolbar
            "[class*=\"toolbar\"]", "[class*=\"nav\"]",
            # Share / action buttons
            "[class*=\"share\"]", "[class*=\"like\"]",
            "[class*=\"reward\"]",
            # Footer / copyright banners
            "[class*=\"footer\"]", "[class*=\"copyright\"]",
            "[class*=\"tip\"]",
            # WeChat-specific UI containers (rich-media extras)
            "[class*=\"extra\"]",
            "[class*=\"ad_\"]",
            "[class*=\"banner\"]",
            "[class*=\"promotion\"]",
            "[data-pluginname]",
        ):
            for tag in soup.select(selector):
                tag.decompose()

        # Also remove by tag role.
        for tag in soup(["script", "style"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)

        return WxMpReportFetcher._clean_article_text(text)

    @staticmethod
    def _clean_article_text(text: str) -> str:
        """Post-extraction cleanup: remove noise lines and truncate at
        known content-end markers found in WeChat MP article footers."""
        import re as _re

        if not text:
            return ""

        # ── First pass: remove individual noise lines ────────────
        noise_re = _re.compile(
            "|".join([
                r"在小说阅读器读本章",
                r"去阅读",
                r"在小说阅读器中沉浸阅读",
                r"在小说阅读器中阅读",
                r"开启沉浸阅读",
                r"^原创$",
                r"^微信扫一扫$",
                r"关注该公众号$",
                r"长按识别前往小程序$",
                r"^赞$",
                r"^在看$",
                r"^听过$",
                r"^视频$",
                r"^小程序$",
                r"^分享$",
                r"^留言$",
                r"^收藏$",
                r"^取消$",
                r"^允许$",
                r"^分析$",
                r"^知道了$",
                r"^使用小程序$",
                r"^使用完整服务$",
                r"轻点两下取消在看",
            ])
        )
        lines = text.split("\n")
        cleaned = [
            ln for ln in lines
            if ln.strip() and not noise_re.match(ln.strip())
        ]
        text = "\n".join(cleaned)

        # ── Second pass: content-end truncation ─────────────────
        # WeChat articles append promotional blocks, recommended-reading
        # sections, and reader UI chrome after the main body.  The first
        # occurrence of any known end marker signals a reliable cutoff.
        cutoff = WxMpReportFetcher._find_content_end(text)
        if cutoff is not None:
            text = text[:cutoff].strip()

        return text

    @staticmethod
    def _find_content_end(text: str) -> Optional[int]:
        """Find the character offset where WeChat footer noise begins.

        Returns ``None`` when no clear content-end marker is found.
        """
        earliest: Optional[int] = None
        for marker in _WEIXIN_CONTENT_END_MARKERS:
            idx = text.find(marker)
            if idx != -1:
                if earliest is None or idx < earliest:
                    earliest = idx
        return earliest
