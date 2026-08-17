"""WeChat MP reports source for the research-reports pipeline.

Fetches WeChat MP articles as research reports via the WeRead channel
(``src.we_read``) — pure HTTP, no Playwright, no external we-mp-rss service.
Registered in ``_SOURCE_REGISTRY`` when ``wxmp`` is listed in config's
``reports.sources``.

Article data is gathered during ``fetch_native_ids`` and cached; ``fetch_detail``
returns Reports from cache with the WeChat content-cleanup applied and an empty
``pdf_urls`` list left for the browser resolver to fill (no extra API calls
needed).
"""

from __future__ import annotations

import json as json_mod
import logging
import re as _re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup, NavigableString

from ...config.constants import WXMP_REPORT_DEFAULTS
from ...models import WxMpConfig, WxMpSourceConfig
from ...scrapers.wxmp import fix_wechat_images, sanitize_wxmp_display_html
from ...we_read import build_client_from_wxmp_config, ensure_login, with_empty_retry
from ...we_read.errors import WeReadAuthError, WeReadError
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
        """Resolve the wxmp config (no we-mp-rss core seeding anymore)."""
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
                )
        return self._wxmp_config

    def _resolve_weread_mp_ids(self) -> Dict[str, str]:
        """Map account names to weread mp_ids from configured feeds."""
        mapping: Dict[str, str] = {}
        if self._wxmp_config and self._wxmp_config.feeds:
            for f in self._wxmp_config.feeds:
                if f.weread_mp_id and f.name not in mapping:
                    mapping[f.name] = f.weread_mp_id
        return mapping

    async def fetch_native_ids(self, client: httpx.AsyncClient) -> List[str]:
        """Gather article IDs from configured accounts via the WeRead channel,
        caching full article data for ``fetch_detail``.

        When the WeRead token is missing or has gone invalid (401), an
        interactive run pops the QR login window and retries once with the
        fresh token; CI / non-interactive runs skip the source fail-open.
        """
        self._ensure_init()
        wc = build_client_from_wxmp_config(self._wxmp_config, http_client=client)
        if not await ensure_login(wc):
            logger.warning(
                "微信读书未登录或登录失效，跳过报告源。可运行 `horizon-wxmp login` 扫码。"
            )
            return []

        login_retried = False
        while True:
            try:
                return await self._fetch_ids(wc)
            except WeReadAuthError as exc:
                if login_retried:
                    logger.warning("微信读书登录失效，跳过报告源: %s", exc)
                    return []
                login_retried = True
                logger.warning("微信读书登录失效，正在弹出扫码窗口重新登录…")
                if await ensure_login(wc, force=True):
                    continue  # 新 token，重试全部账号
                return []

    async def _fetch_ids(self, wc) -> List[str]:
        """List each configured account's articles; 401 propagates up to
        ``fetch_native_ids`` so it can trigger a re-login."""
        name_to_mp = self._resolve_weread_mp_ids()
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.cfg.max_age_days)
        cutoff_ts = cutoff.timestamp()
        all_ids: List[str] = []
        self._article_cache = {}

        for name in self.cfg.account_names:
            mp_id = name_to_mp.get(name)
            if not mp_id:
                logger.warning("账号 %r 缺少 weread_mp_id — 跳过", name)
                continue
            try:
                arts = await with_empty_retry(
                    lambda: self._gather_feed_weread(wc, name, mp_id),
                    waits=self._wxmp_config.weread.empty_retry_waits,
                    max_empties=self._wxmp_config.weread.empty_max_retries,
                    log=logger,
                    ctx=f"报告源 {name}",
                )
            except WeReadAuthError:
                raise  # 401 → 交回 fetch_native_ids() 处理重新登录
            except WeReadError as exc:
                logger.warning("抓取报告源 %r 失败: %s", name, exc)
                continue
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

    async def _gather_feed_weread(self, wc, name: str, mp_id: str) -> List[dict]:
        """List one account's articles via we_read, normalized to art-dict shape."""
        arts: List[dict] = []
        for art in await wc.list_articles(mp_id, page=1):
            content = ""
            if self.cfg.gather_content and art.url:
                try:
                    raw = await wc.fetch_article_html(art.url)
                    content = fix_wechat_images(raw)
                except WeReadError as exc:
                    # 单篇正文失败(302/风控/失效/网络) → 正文留空、报告保留。
                    logger.warning(
                        "报告源 %r 正文抓取失败，跳过正文: %s", name, exc
                    )
            arts.append(
                {
                    "id": art.id,
                    "mp_id": mp_id,
                    "title": art.title,
                    "url": art.url,
                    "pic_url": art.pic_url,
                    "publish_time": art.publish_time,
                    "description": "",
                    "content": content,
                }
            )
        return arts

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

        raw = article.get("content") or None
        display_html = sanitize_wxmp_display_html(raw) if raw else ""

        content_text = self._extract_text(article["content"])
        content_fallback = False

        # Fallback: cached content too short → fetch article URL directly.
        if not content_text or len(content_text) < 100:
            fetched = await self._fetch_content_from_url(client, article.get("link", ""))
            if fetched and len(fetched) > len(content_text):
                content_text = self._clean_article_text(fetched)
                content_fallback = True
                # 回退路径的缓存 HTML 是不可信的短 stub，生成 display_html 只会
                # 更差 —— 置空，前端自动回退到 content_text 纯文本渲染。
                display_html = ""

        # When content is still empty/short after fallback, the browser
        # resolver can still load the article and try the 阅读原文 /
        # QR-code strategies — skip the AI relevance filter so the article
        # isn't discarded before reaching that stage.
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
            raw_html=raw,
            display_html=display_html or None,
            categories=[],
            published_at=published_at,
            updated_at=published_at,
            fetched_at=datetime.now(timezone.utc),
            skip_ai_filter=article.get("is_featured", False) or needs_browser,
            pdf_urls=[],
        )

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
