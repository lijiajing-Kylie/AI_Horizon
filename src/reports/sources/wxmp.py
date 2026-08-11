"""WeChat MP reports source for the research-reports pipeline.

Fetches WeChat MP articles as research reports via the bundled we-mp-rss core
(``src.we_mp_rss``) — no external we-mp-rss Docker service.  Registered in
``_SOURCE_REGISTRY`` when ``wxmp`` is listed in config's ``reports.sources``.

Article data is gathered during ``fetch_native_ids`` and cached; ``fetch_detail``
returns Reports from cache with we-mp-rss's content-cleanup + keyword-gated PDF
detection applied (no extra API calls needed).
"""

from __future__ import annotations

import asyncio
import json as json_mod
import logging
import re as _re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup, NavigableString

from ...config.constants import WXMP_REPORT_DEFAULTS
from ...models import WxMpConfig, WxMpSourceConfig
from ...scrapers.wxmp import faker_id_from_feed_id
from ..models import Report
from .base import ReportSourceFetcher

logger = logging.getLogger(__name__)

# ── WeChat article content-end markers ──────────────────────────────────
_WEIXIN_CONTENT_END_MARKERS = [
    "推荐阅读",
    "投稿及任何意见可以联系",
    "如若您期待获得《互联网前沿》杂志",
    "纸质刊物获取地址",
    "纸刊获取链接",
    "👇 点个",
    '点个"在看"',
    '点个在看',
    "分享洞见",
    "预览时标签不可点",
    "微信扫一扫可打开此内容",
    "使用完整服务",
]

# ── Inline tags: no newline between these when extracting text ───────────
# WeChat wraps individual text fragments in <span>/<em>/<strong>, so a naive
# ``get_text(separator="\n")`` shreds one paragraph into one fragment per line
# (a ``（…）`` parenthetical on its own line, or a run of single commas).
_INLINE_TAGS = {
    "span", "em", "strong", "a", "b", "i", "u", "font", "small", "sub",
    "sup", "code", "mark", "s", "strike", "del", "ins", "abbr", "cite",
    "time", "label", "q", "tt", "var", "big", "kbd", "samp",
}

# ── WeChat keyword-gated PDF detection ───────────────────────────────────
_QUOTED_KW_RE = _re.compile(
    '(?:回复|输入|发送|关键词)\\s*[：:\\s]*'
    '(?:'
    '"([^"]{1,40})"'           # "keyword" (ASCII double)
    '|'
    '「([^」]{1,40})」'        # 「keyword」(corner)
    '|'
    '『([^』]{1,40})』'        # 『keyword』(white corner)
    '|'
    '“([^“]{1,40})”'   # "keyword" (smart double)
    '|'
    '‘([^‘]{1,40})’'   # 'keyword' (smart single)  # noqa: RUF001
    ')'
)

_UNQUOTED_KW_RE = _re.compile(
    '(?:回复|输入|发送)\\s*'
    '(?P<keyword>(?!关键词)[^，。、\\s"\'“”‘’'
    '「『」』]{2,30}?)'
    '\\s*(?:获取|下载|领取).*?(?:PDF|报告)'
)

_GATE_CONTEXT_RE = _re.compile(
    '关注\\s*(?P<account>[^，。\\s]{2,20}?)\\s*(?:公众号|微信公众号|微信)'
)


class WxMpReportConfig:
    """微信报告源配置：从内置 we-mp-rss 核心获取公众号文章作为报告。

    默认值定义在 src/config/constants.py 的 WXMP_REPORT_DEFAULTS 中。
    """

    def __init__(
        self,
        account_names: Optional[List[str]] = None,
        max_age_days: int = WXMP_REPORT_DEFAULTS["max_age_days"],
        fetch_limit: int = WXMP_REPORT_DEFAULTS["fetch_limit"],
        known_feeds: Optional[Dict[str, str]] = None,
        wxmp: Optional[WxMpConfig] = None,
        data_dir: str = "data/wxmp",
        gather_content: bool = True,
        max_page: int = 1,
        gather_interval: int = 3,
    ) -> None:
        self.account_names = account_names or []
        self.max_age_days = max_age_days
        self.fetch_limit = fetch_limit
        # Fallback mapping: account name → feed_id (e.g. from config.sources.wxmp.feeds).
        self.known_feeds = known_feeds or {}
        self.wxmp = wxmp  # Full WxMpConfig from config.sources.wxmp, when available.
        self.data_dir = data_dir
        self.gather_content = gather_content
        self.max_page = max_page
        self.gather_interval = gather_interval


class WxMpReportFetcher(ReportSourceFetcher):
    """Fetcher for WeChat MP articles treated as research reports.

    Article data is cached from the vendored-core gather — ``fetch_detail``
    returns Reports from cache rather than making extra API calls.
    """

    source_name = "wxmp"

    def __init__(self, config: Optional[WxMpReportConfig] = None) -> None:
        self.cfg = config or WxMpReportConfig()
        # Cache: native_id → article dict (populated during fetch_native_ids)
        self._article_cache: Dict[str, dict] = {}
        self._wxmp_config: Optional[WxMpConfig] = None

    def _ensure_init(self) -> WxMpConfig:
        """Seed the bundled we-mp-rss core with a WxMpConfig (idempotent)."""
        import src.we_mp_rss

        if self._wxmp_config is None:
            if self.cfg.wxmp is not None:
                self._wxmp_config = self.cfg.wxmp
            else:
                known = dict(self.cfg.known_feeds or {})
                feeds = [
                    WxMpSourceConfig(name=n, feed_id=fid) for n, fid in known.items()
                ]
                self._wxmp_config = WxMpConfig(
                    feeds=feeds,
                    data_dir=self.cfg.data_dir,
                    gather_content=self.cfg.gather_content,
                    max_page=self.cfg.max_page,
                    gather_interval=self.cfg.gather_interval,
                )
        src.we_mp_rss.init(self._wxmp_config, self._wxmp_config.data_dir)
        return self._wxmp_config

    def _resolve_feed_ids(self) -> Dict[str, str]:
        """Map account names to feed IDs from known_feeds (+ configured feeds)."""
        mapping: Dict[str, str] = dict(self.cfg.known_feeds or {})
        if self._wxmp_config and self._wxmp_config.feeds:
            for f in self._wxmp_config.feeds:
                if f.feed_id and f.name not in mapping:
                    mapping[f.name] = f.feed_id
        return mapping

    async def fetch_native_ids(self, client: httpx.AsyncClient) -> List[str]:
        """Gather article IDs from configured accounts within the time window,
        caching full article data for ``fetch_detail``."""
        self._ensure_init()
        from src.we_mp_rss.driver.success import CanGetToken

        if not CanGetToken():
            logger.warning(
                "WeChat MP 未登录或登录态已过期，跳过报告源。运行 `horizon-wxmp login` 后重试。"
            )
            return []

        name_to_id = self._resolve_feed_ids()
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.cfg.max_age_days)
        cutoff_ts = cutoff.timestamp()
        all_ids: List[str] = []
        self._article_cache = {}

        for name in self.cfg.account_names:
            feed_id = name_to_id.get(name)
            if not feed_id:
                logger.warning("Unknown WeChat account %r — skipping", name)
                continue
            faker_id = faker_id_from_feed_id(feed_id)
            if not faker_id:
                logger.warning(
                    "无法从 feed_id %r 推导 fakeid（特殊 feed，跳过）", feed_id
                )
                continue

            arts = await asyncio.to_thread(
                self._gather_feed_sync, faker_id, feed_id, name
            )
            for art in arts:
                ts = art.get("publish_time")
                if ts is None:
                    continue
                try:
                    ts = float(ts)
                except (TypeError, ValueError):
                    continue
                if ts < cutoff_ts:
                    continue

                article_id = str(art.get("id", ""))
                if not article_id:
                    continue
                self._cache_article(article_id, art, name)
                if article_id not in all_ids:
                    all_ids.append(article_id)

        return all_ids

    def _gather_feed_sync(
        self, faker_id: str, feed_id: str, name: str
    ) -> List[dict]:
        """Gather one account's articles through the vendored we-mp-rss core."""
        from src.we_mp_rss.core.wx.base import WxGather

        def collect(_art: dict) -> bool:
            return True

        wx = WxGather().Model("web")
        wx.get_Articles(
            faker_id=faker_id,
            Mps_id=feed_id,
            Mps_title=name,
            CallBack=collect,
            MaxPage=self.cfg.max_page,
            interval=self.cfg.gather_interval,
            Gather_Content=self.cfg.gather_content,
        )
        return getattr(wx, "articles", []) or []

    def _cache_article(self, article_id: str, art: dict, feed_name: str) -> None:
        """Store a single gathered article in ``_article_cache``."""
        self._article_cache[article_id] = {
            "id": article_id,
            "title": art.get("title", "Untitled"),
            "description": art.get("description") or "",
            "content": art.get("content") or "",
            "link": art.get("url", ""),
            "channel_name": feed_name,
            "updated": art.get("publish_time", 0),
            "image": art.get("pic_url", ""),
            "is_featured": False,
        }

    async def fetch_detail(
        self, client: httpx.AsyncClient, native_id: str
    ) -> Optional[Report]:
        """Return a Report from the article data cached in ``fetch_native_ids``.

        When the gathered ``content`` field is empty or too short, falls back
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

        # When content is still empty/short after fallback, the browser
        # resolver can still load the article and detect any
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
            raw_html=article.get("content") or None,
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
        """Scan *text* for patterns like "关注XX公众号，回复关键词获取PDF"."""
        if not text:
            logger.info(
                "Empty text for channel=%r — skipping keyword detection",
                channel_name,
            )
            return None
        if len(text) < 15:
            logger.info(
                "Text too short (%d chars) for channel=%r — skipping keyword detection",
                len(text),
                channel_name,
            )
            return None

        keyword: Optional[str] = None
        account = channel_name

        m = _QUOTED_KW_RE.search(text)
        if m:
            if m.lastindex is not None:
                kw = m.group(m.lastindex)
                if kw:
                    keyword = kw.strip()
        else:
            m = _UNQUOTED_KW_RE.search(text)
            if m:
                keyword = (m.group("keyword") or "").strip()

        if not keyword:
            logger.info(
                "No wechat keyword pattern in %d chars of text, channel=%r",
                len(text),
                channel_name,
            )
            return None

        m = _GATE_CONTEXT_RE.search(text)
        if m:
            acct = (m.group("account") or "").strip()
            if acct:
                account = acct

        logger.info(
            "Detected WeChat keyword gate: account=%r keyword=%r", account, keyword
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
            brief = article.get("title", "")[:60]
            if content_text:
                logger.info(
                    "No wechat keyword in %d-char content for %r; "
                    "last 300 chars: %r",
                    len(content_text),
                    brief,
                    content_text[-300:],
                )
            else:
                logger.info(
                    "Empty content_text for %r — bundled we-mp-rss content may "
                    "be truncated or missing",
                    brief,
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

        content_el = soup.select_one("#js_content")
        if content_el:
            text = WxMpReportFetcher._block_level_text(content_el)
            if len(text) > 100:
                return text

        for sel in ("article", "[class*=\"article\"]", "[class*=\"content\"]", "main"):
            els = soup.select(sel)
            if els:
                text = "\n".join(
                    WxMpReportFetcher._block_level_text(el) for el in els
                )
                if len(text) > 100:
                    return text

        body = soup.find("body")
        if body:
            text = WxMpReportFetcher._block_level_text(body)
            if len(text) > 100:
                return text

        return ""

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
        """Strip HTML tags to get clean plain text."""
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")

        for selector in (
            "svg", "noscript", "iframe",
            "[class*=\"novel\"]", "[class*=\"reader\"]",
            "[class*=\"read_\"]", "[id*=\"novel\"]", "[id*=\"reader\"]",
            "[class*=\"toolbar\"]", "[class*=\"nav\"]",
            "[class*=\"share\"]", "[class*=\"like\"]",
            "[class*=\"reward\"]",
            "[class*=\"footer\"]", "[class*=\"copyright\"]",
            "[class*=\"tip\"]",
            "[class*=\"extra\"]",
            "[class*=\"ad_\"]",
            "[class*=\"banner\"]",
            "[class*=\"promotion\"]",
            "[data-pluginname]",
        ):
            for tag in soup.select(selector):
                tag.decompose()

        for tag in soup(["script", "style"]):
            tag.decompose()

        text = WxMpReportFetcher._block_level_text(soup)

        return WxMpReportFetcher._clean_article_text(text)

    @staticmethod
    def _block_level_text(container) -> str:
        """Extract text with newlines only at block-level boundaries.

        ``get_text(separator="\\n")`` is unsuitable: it uses
        ``separator.join(strings)`` over *every* NavigableString, so the
        inline ``<span>/<em>/<strong>`` wrappers WeChat uses to style single
        fragments shred one paragraph into a fragment per line (a ``（…）``
        parenthetical alone on its line, or a run of single commas).  This
        recursion walks the DOM instead, emitting a newline only at block
        boundaries and ``<br>`` while inline tags are joined seamlessly.
        """
        clone = BeautifulSoup(str(container), "html.parser")

        def _collapse(s: str) -> str:
            # Tag-separator whitespace (indentation/newlines between tags)
            # lands in text nodes and must not become line breaks; collapse
            # it to single spaces and drop pure-whitespace nodes.
            return _re.sub(r"\s+", " ", s).strip()

        def _walk(node) -> list:
            frags: list[str] = []
            if isinstance(node, NavigableString):
                s = _collapse(str(node))
                return [s] if s else []
            inline = node.name in _INLINE_TAGS
            for child in node.children:
                if isinstance(child, NavigableString):
                    s = _collapse(str(child))
                    if s:
                        frags.append(s)
                elif child.name == "br":
                    frags.append("\n")
                else:
                    frags.extend(_walk(child))
                    if not inline and child.name not in _INLINE_TAGS:
                        frags.append("\n")
            return frags

        return "".join(_walk(clone))

    @staticmethod
    def _clean_article_text(text: str) -> str:
        """Post-extraction cleanup: remove noise lines and truncate at
        known content-end markers found in WeChat MP article footers."""
        if not text:
            return ""

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

        cutoff = WxMpReportFetcher._find_content_end(text)
        if cutoff is not None:
            text = text[:cutoff].strip()

        return text

    @staticmethod
    def _merge_text_fragments(text: str) -> str:
        """Re-join fragments shredded by the pre-``_block_level_text`` extractor.

        Reports fetched under the old ``get_text(separator="\\n")`` logic kept
        a ``content_text`` whose parentheticals and inline fragments were
        split onto their own lines (e.g. ``自主实验室`` / ``（`` / ``SDL`` /
        ``）``).  With only plain text left there is no HTML to re-parse, so
        this re-flows heuristically: bracket fragments, bare punctuation
        lines and continuation fragments are joined onto the adjacent body
        line.  Only ever joins; a clean paragraph is left untouched.
        """
        lines = [ln.strip() for ln in text.split("\n")]
        out: list[str] = []
        i, n = 0, len(lines)
        # 续写开头:属于上一句的延续(被拆碎的句子后半段)。
        CONTINUATION = {"的", "了", "、", "。", "，", "；", "：", "）", ")"}

        def append_frag(frag: str) -> None:
            if out:
                out[-1] += frag
            else:
                out.append(frag)

        while i < n:
            s = lines[i]
            if not s:
                i += 1
                continue

            # 左括号开跨行碎片:( … ) 收集完整后挂到上一行。
            if s.startswith("（") and "）" not in s:
                buf = s
                i += 1
                while i < n and "）" not in buf:
                    nxt = lines[i].strip()
                    if nxt:
                        buf += nxt
                    i += 1
                append_frag(buf)
                continue

            # 单标点行。
            if len(s) <= 2 and s in {"（", "）", "。", "，", "；", "：", "、", "(", ")", "."}:
                append_frag(s)
                i += 1
                continue

            # 独立完整括号行 (…),较短 → 属于上一句的括号注释。
            if s.startswith("（") and s.endswith("）") and len(s) <= 60:
                append_frag(s)
                i += 1
                continue

            # 以续写词开头的行 → 上一句的后半段。
            if s[0] in CONTINUATION:
                append_frag(s)
                i += 1
                continue

            out.append(s)
            i += 1

        return "\n".join(out)

    @staticmethod
    def _find_content_end(text: str) -> Optional[int]:
        """Find the character offset where WeChat footer noise begins."""
        earliest: Optional[int] = None
        for marker in _WEIXIN_CONTENT_END_MARKERS:
            idx = text.find(marker)
            if idx != -1:
                if earliest is None or idx < earliest:
                    earliest = idx
        return earliest
